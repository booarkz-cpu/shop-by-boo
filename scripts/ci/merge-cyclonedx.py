#!/usr/bin/env python3
"""Merge CycloneDX dependency graphs into one deterministic release SBOM."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _key(component: dict[str, Any]) -> tuple[str, ...]:
    if component.get("purl"):
        return ("purl", component["purl"])
    if component.get("cpe"):
        return ("cpe", component["cpe"])
    return (
        "coordinates",
        component.get("type", "library"),
        component.get("group", ""),
        component.get("name", ""),
        component.get("version", ""),
    )


def _canonical_ref(key: tuple[str, ...]) -> str:
    value = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
    return "urn:shop-by-boo:component:" + hashlib.sha256(value.encode()).hexdigest()


def _resolved_keys(candidates: list[dict], dependencies: list[dict]) -> dict[str, tuple[str, ...]]:
    keys = {}
    for item in candidates:
        ref = item.get("bom-ref")
        if ref:
            key = _key(item)
            if keys.setdefault(ref, key) != key:
                raise ValueError(f"conflicting CycloneDX reference {ref}")

    children = defaultdict(set)
    for row in dependencies:
        children[row.get("ref")].update(row.get("dependsOn") or [])

    # Trivy can report the same package version twice with different optional
    # dependencies. Split such instances, then propagate the split to their parents.
    # Each pass only subdivides groups, including when the graph contains cycles.
    while True:
        refs = {ref: _canonical_ref(key) for ref, key in keys.items()}
        groups = defaultdict(lambda: defaultdict(list))
        for ref, key in keys.items():
            try:
                outgoing = tuple(sorted({refs[child] for child in children.get(ref, ())}))
            except KeyError as exc:
                raise ValueError(f"unresolved CycloneDX dependency {exc.args[0]}") from exc
            groups[key][outgoing].append(ref)
        changes = {}
        for key, variants in groups.items():
            if len(variants) > 1:
                for outgoing, members in variants.items():
                    variant = (*key, "dependsOn", _canonical_ref(outgoing))
                    changes.update(dict.fromkeys(members, variant))
        if not changes:
            return keys
        keys.update(changes)


def _merge_lists(left: list[Any], right: list[Any]) -> list[Any]:
    values = {json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")): value
              for value in [*left, *right]}
    return [values[key] for key in sorted(values)]


def _merge_component(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(current)
    for name, value in incoming.items():
        if name == "bom-ref":
            continue
        if name not in result or result[name] in (None, "", []):
            result[name] = copy.deepcopy(value)
        elif isinstance(result[name], list) and isinstance(value, list):
            result[name] = _merge_lists(result[name], value)
        elif isinstance(result[name], dict) and isinstance(value, dict):
            result[name] = _merge_component(result[name], value)
    return result


def _timestamp(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def merge_documents(
    documents: list[dict[str, Any]],
    *,
    source_date_epoch: int,
    root_name: str | None = None,
    root_version: str | None = None,
) -> dict[str, Any]:
    if not documents:
        raise ValueError("at least one CycloneDX input is required")
    for document in documents:
        if document.get("bomFormat") != "CycloneDX" or not document.get("specVersion"):
            raise ValueError("not a CycloneDX document")

    components: dict[tuple[str, ...], dict[str, Any]] = {}
    refs_by_document: list[dict[str, str]] = []
    roots: list[str] = []
    selected_root_key: tuple[str, ...] | None = None

    metadata = {}
    vulnerabilities = []
    for document in documents:
        mapping: dict[str, str] = {}
        candidates = list(document.get("components") or [])
        metadata_root = (document.get("metadata") or {}).get("component")
        if metadata_root:
            candidates.append(metadata_root)
        resolved = _resolved_keys(candidates, document.get("dependencies") or [])
        # Trivy orders components by random IDs. Identical PURLs can have different display
        # names (e.g. SQLAlchemy/sqlalchemy), so choose their metadata in a stable order.
        ordered = sorted(candidates, key=lambda item: json.dumps(
            {key: value for key, value in item.items() if key != "bom-ref"}, ensure_ascii=False, sort_keys=True))
        for candidate in ordered:
            candidate = copy.deepcopy(candidate)
            old_ref = candidate.get("bom-ref")
            key = resolved[old_ref] if old_ref else _key(candidate)
            ref = _canonical_ref(key)
            if old_ref:
                mapping[old_ref] = ref
            candidate["bom-ref"] = ref
            if key in components:
                components[key] = _merge_component(components[key], candidate)
            else:
                components[key] = candidate
        if metadata_root:
            root_key = resolved.get(metadata_root.get("bom-ref"), _key(metadata_root))
            roots.append(_canonical_ref(root_key))
            if selected_root_key is None or metadata_root.get("name") == "shop-by-boo":
                selected_root_key = root_key
        refs_by_document.append(mapping)
        source_metadata = document.get("metadata", {})
        metadata = _merge_component(metadata, {k: v for k, v in source_metadata.items()
                                               if k not in {"timestamp", "component"}})
        for original in document.get("vulnerabilities", []):
            finding = copy.deepcopy(original)
            if "bom-ref" in finding:
                finding["bom-ref"] = _canonical_ref(("vulnerability", finding["id"], finding.get("source", {}).get("name", "")))
            for target in finding.get("affects", []):
                if target["ref"] not in mapping:
                    raise ValueError(f"unresolved vulnerability target {target['ref']}")
                target["ref"] = mapping[target["ref"]]
            vulnerabilities.append(finding)

    if root_name:
        synthetic_root = {
            "type": "application",
            "name": root_name,
            "version": root_version or "unspecified",
            "purl": f"pkg:github/booarkz-cpu/{root_name}@{root_version or 'unspecified'}",
        }
        root_key = _key(synthetic_root)
        selected_root_key = root_key
        synthetic_root["bom-ref"] = _canonical_ref(root_key)
        if root_key in components:
            components[root_key] = _merge_component(components[root_key], synthetic_root)
        else:
            components[root_key] = synthetic_root

    relationships: dict[str, set[str]] = defaultdict(set)
    for document, mapping in zip(documents, refs_by_document, strict=True):
        for dependency in document.get("dependencies") or []:
            ref = mapping.get(dependency.get("ref"))
            if not ref:
                raise ValueError(f"unresolved CycloneDX dependency {dependency.get('ref')}")
            for item in dependency.get("dependsOn") or []:
                if item not in mapping:
                    raise ValueError(f"unresolved CycloneDX dependency {item}")
                relationships[ref].add(mapping[item])

    if selected_root_key is None:
        raise ValueError("every input is missing metadata.component")
    # The product root belongs in metadata.component and in dependencies.
    selected_root = components.pop(selected_root_key)
    root_ref = selected_root["bom-ref"]
    relationships[root_ref].update(ref for ref in roots if ref != root_ref)
    for component in components.values():
        relationships.setdefault(component["bom-ref"], set())

    ordered_components = sorted(components.values(), key=lambda item: item["bom-ref"])
    dependencies = [
        {"ref": ref, "dependsOn": sorted(depends_on)}
        for ref, depends_on in sorted(relationships.items())
    ]
    metadata["component"] = copy.deepcopy(selected_root)
    metadata["properties"] = _merge_lists(metadata.get("properties", []), [
        {"name": "shop-by-boo:sbom:input-count", "value": str(len(documents))},
        {"name": "shop-by-boo:sbom:android-graphs", "value": str(max(0, len(documents) - 1))},
    ])
    result = {
        "bomFormat": "CycloneDX",
        "specVersion": max((document["specVersion"] for document in documents),
                           key=lambda version: tuple(map(int, version.split(".")))),
        "version": 1,
        "metadata": metadata,
        "components": ordered_components,
        "dependencies": dependencies,
    }
    if any("vulnerabilities" in document for document in documents):
        result["vulnerabilities"] = _merge_lists([], vulnerabilities)
    for document in documents:
        if document.get("$schema") and document["specVersion"] == result["specVersion"]:
            result["$schema"] = document["$schema"]
            break
    set_identity(result, source_date_epoch)
    return result


def set_identity(document: dict[str, Any], source_date_epoch: int) -> None:
    document["metadata"]["timestamp"] = _timestamp(source_date_epoch)
    document.pop("serialNumber", None)
    identity = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    document["serialNumber"] = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def write_bom(document: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    output.write_bytes(payload)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {output.name}\n", encoding="utf-8"
    )


def merge(inputs: list[Path], output: Path, *, source_date_epoch: int,
          root_name: str | None = None, root_version: str | None = None) -> dict[str, Any]:
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(inputs)]
    result = merge_documents(documents, source_date_epoch=source_date_epoch, root_name=root_name, root_version=root_version)
    write_bom(result, output)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-date-epoch", type=int, default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")))
    parser.add_argument("--root-name")
    parser.add_argument("--root-version")
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    merged = merge(
        args.inputs,
        args.output,
        source_date_epoch=args.source_date_epoch,
        root_name=args.root_name,
        root_version=args.root_version,
    )
    print(f"SBOM: {len(merged['components'])} components, {len(merged['dependencies'])} dependency nodes")


if __name__ == "__main__":
    main()
