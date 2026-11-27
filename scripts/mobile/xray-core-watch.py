#!/usr/bin/env python3
"""Open a versioned mobile update only when the AndroidLibXrayLite source commit changes.

The standalone client and VPN Shop embed the same AAR. Shop and Lucy Admin share a version
across Android and iOS. Update all release identities, retain the previous distribution's
download versions, and prepare the source-backed release notes after the version commit.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/audit"))
from check_release_changelog import COLUMNS, current_mobile_tag, gradle_version, mobile_version, validate_client, validate_mobile  # noqa: E402

AAR = ROOT / "scripts/mobile/build-xray-aar.sh"
GRADLE = ROOT / "apps/vpn-client/android/app/build.gradle.kts"
NOTES = ROOT / "docs/ru/new/ANDROID_CLIENT_APP.md"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
SHOP = ROOT / "apps/vpn-shop/android/app/build.gradle.kts"
ADMIN = ROOT / "apps/lucy-admin/android/app/build.gradle.kts"
IOS = (
    ROOT / "apps/vpn-shop/ios/VpnShopUser.xcodeproj/project.pbxproj",
    ROOT / "apps/lucy-admin/ios/VpnShopAdmin.xcodeproj/project.pbxproj",
)
READMES = {
    "README.md": ("Магазин и Lucy Admin · Android и iOS", "VPN-клиент · Android"),
    "README.en.md": ("Shop and Lucy Admin · Android and iOS", "VPN client · Android"),
    "README.uk.md": ("Магазин і Lucy Admin · Android та iOS", "VPN-клієнт · Android"),
}
COMMIT_LINE = re.compile(r'^COMMIT="\$\{XRAY_AAR_COMMIT:-([0-9a-f]{40})\}"$', re.M)
TAG = re.compile(r"^v?\d{1,4}\.\d{1,4}\.\d{1,4}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
NOTICE_PIN = re.compile(
    r"^(- \[AndroidLibXrayLite\]\(https://github\.com/2dust/AndroidLibXrayLite\)[^\n]*?тег )"
    r"`[^`\n]+`(, ревизия )`([0-9a-f]{40})`", re.M,
)


def current_commit(script: str) -> str:
    found = COMMIT_LINE.search(script)
    if not found:
        raise ValueError("no pinned COMMIT in build-xray-aar.sh")
    return found.group(1)


def set_commit(script: str, commit: str) -> str:
    if not SHA.fullmatch(commit):
        raise ValueError("commit: 40 hex")
    return COMMIT_LINE.sub(f'COMMIT="${{XRAY_AAR_COMMIT:-{commit}}}"', script, count=1)


def update_notice(notices: str, old: str, tag: str, commit: str) -> str:
    matches = list(NOTICE_PIN.finditer(notices))
    if len(matches) != 1 or matches[0].group(3) != old:
        raise ValueError("THIRD_PARTY_NOTICES.md must name the current AndroidLibXrayLite commit exactly once")
    match = matches[0]
    new = f"{match[1]}`{tag}`{match[2]}`{commit}`"
    return notices[:match.start()] + new + notices[match.end():]


def bump_android(gradle: str, code_step: int) -> tuple[str, str]:
    name, code = gradle_version(gradle)
    major, minor, patch = map(int, name.split("."))
    next_name = f"{major}.{minor}.{patch + 1}"
    if code + code_step > 2_100_000_000:
        raise ValueError("Android versionCode limit exceeded")
    gradle = re.sub(rf'^(\s*versionName\s*=\s*)"{re.escape(name)}"(?=[ \t]*$)',
                    rf'\g<1>"{next_name}"', gradle, flags=re.MULTILINE)
    gradle = re.sub(rf"^(\s*versionCode\s*=\s*){code}(?=[ \t]*$)",
                    rf"\g<1>{code + code_step}", gradle, flags=re.MULTILINE)
    return gradle, next_name


def ios_version(project: str, old: tuple[str, int], new: tuple[str, int]) -> str:
    for key, before, after in zip(("MARKETING_VERSION", "CURRENT_PROJECT_VERSION"), old, new, strict=True):
        pattern = rf"(\b{key}\s*=\s*)([^;\s]+)(\s*;)"
        matches = re.findall(pattern, project)
        if not matches or {value for _, value, _ in matches} != {str(before)}:
            raise ValueError(f"iOS {key} does not match Android release family")
        project = re.sub(pattern, rf"\g<1>{after}\g<3>", project)
    return project


def table_version(text: str, label: str, old_columns: str, new_columns: str) -> str:
    # Only the last source columns of the named row change. Historical download columns stay pinned.
    pattern = rf"^(\| {re.escape(label)} \| [^|\n]+ \| ){re.escape(old_columns)}( \|)$"
    text, count = re.subn(pattern, rf"\g<1>{new_columns}\g<2>", text, flags=re.MULTILINE)
    if count != 1:
        raise ValueError(f"Expected one current source version row for {label}")
    return text


def family_update(old_client: tuple[str, int], new_client: tuple[str, int]) -> dict[Path, str]:
    old = gradle_version(SHOP.read_text())
    if gradle_version(ADMIN.read_text()) != old:
        raise ValueError("Shop and admin Android versions differ")
    files = {p: bump_android(p.read_text(), 10)[0] for p in (SHOP, ADMIN)}
    new = gradle_version(files[SHOP])
    files.update({p: ios_version(p.read_text(), old, new) for p in IOS})
    for filename, (family_label, client_label) in READMES.items():
        p = ROOT / filename
        page = table_version(p.read_text(), family_label, old[0], new[0])
        files[p] = table_version(page, client_label, old_client[0], new_client[0])
    overview = ROOT / "MOBILE.md"
    page = overview.read_text()
    for label, before, after in (("VPN Shop", old, new), ("Lucy Admin", old, new), ("Корги Люси: клиент", old_client, new_client)):
        page = table_version(page, label, f"{before[0]} | {before[1]}", f"{after[0]} | {after[1]}")
    files[overview] = page
    return files


def note(notes: str, version: str, tag: str, commit: str) -> str:
    """A section of the client's notes above the latest one."""
    entry = (f"## Версия {version} — ядро Xray из AndroidLibXrayLite {tag}\n\n"
             f"- Подготовлено обновление ядра (N11): AndroidLibXrayLite {tag}, коммит `{commit}`. "
             "Сборка AAR, unit-тесты и VPN/TUN на эмуляторе требуют подтверждения успешным CI "
             "точного коммита PR; до завершения проверок результат не подтверждён.\n\n")
    first = notes.find("\n## ")
    return notes[: first + 1] + entry + notes[first + 1:] if first >= 0 else notes + "\n" + entry


def write_update(files: dict[Path, str]) -> None:
    """Stage the entire version change before installing files, and restore prior contents on failure."""
    with tempfile.TemporaryDirectory(dir=ROOT, prefix=".xray-watch-") as work:
        staged = []
        for index, (path, content) in enumerate(files.items()):
            backup = Path(work) / f"{index}.original"
            updated = Path(work) / f"{index}.updated"
            if path.exists():
                shutil.copy2(path, backup)
            updated.write_text(content)
            if backup.exists():
                shutil.copymode(backup, updated)
            staged.append((path, backup, updated))

        installed = []
        try:
            for path, backup, updated in staged:
                updated.replace(path)
                installed.append((path, backup))
        except OSError:
            for path, backup in reversed(installed):
                if backup.exists():
                    backup.replace(path)
                else:
                    path.unlink()
            raise


def check_against(base: str) -> None:
    if not SHA.fullmatch(base):
        raise ValueError("Expected a full base commit")
    def before(path: Path) -> str:
        return subprocess.check_output(["git", "show", f"{base}:{path.relative_to(ROOT)}"], cwd=ROOT, text=True)
    if current_commit(before(AAR)) == current_commit(AAR.read_text()):
        return
    family = mobile_version(ROOT, "vpn-shop")
    current_mobile_tag(ROOT)
    for project in IOS:
        ios_version(project.read_text(), family, family)
    for path in (SHOP, ADMIN, GRADLE):
        old_name, old_code = gradle_version(before(path))
        new_name, new_code = gradle_version(path.read_text())
        if (new_code <= old_code or tuple(map(int, new_name.split("."))) <= tuple(map(int, old_name.split(".")))):
            raise ValueError(f"Changed shared Android engine requires higher versionName and versionCode in {path.relative_to(ROOT)}")


def release_notes(tag: str, pin: str) -> None:
    """Link the release tables to the actual first commit of the watcher's PR."""
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    sources = (AAR, GRADLE, SHOP, ADMIN, *IOS, NOTICES)
    subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *sources], cwd=ROOT, check=True)
    source = git("rev-parse", "HEAD")
    def parent(p: Path) -> str:
        return git("show", f"HEAD^:{p.relative_to(ROOT)}")

    previous_pin = current_commit(parent(AAR))
    notices = NOTICES.read_text()
    if current_commit(AAR.read_text()) != pin or previous_pin == pin or update_notice(notices, pin, tag, pin) != notices:
        raise ValueError("Commit the actual new engine pin, tag and notice before writing release notes")
    family = mobile_version(ROOT, "vpn-shop")
    client = mobile_version(ROOT, "vpn-client")
    for p, current, step in ((SHOP, family, 10), (GRADLE, client, 1)):
        if gradle_version(bump_android(parent(p), step)[0]) != current:
            raise ValueError(f"Expected the next version and build for {p.relative_to(ROOT)}")
    mobile = current_mobile_tag(ROOT)
    client_tag = "client-v" + client[0]
    source_link = f"[Коммит обновления](https://github.com/booarkz-cpu/shop-by-boo/commit/{source})"
    upstream = f"[Исходники AndroidLibXrayLite](https://github.com/2dust/AndroidLibXrayLite/commit/{pin})"
    table = "| " + " | ".join(COLUMNS) + " |\n| " + " | ".join(["---"] * len(COLUMNS)) + " |\n"
    client_row = (f"| Самостоятельный Android-клиент | Обновили закреплённую ревизию встроенного VPN-движка | "
                  f"Клиент {client[0]} ({client[1]}) собирается с AndroidLibXrayLite {tag}. Исходный коммит обвязки "
                  f"изменён с `{previous_pin}` на `{pin}`. | Установите подписанный APK клиента поверх ранее установленной версии. "
                  f"| Сборка сверяет метку исходников AAR и нативные библиотеки в APK. Перед публикацией выполняется "
                  f"установка поверх предыдущего подписанного пакета. | {source_link} · {upstream} |\n")
    family_row = (f"| Магазин и Lucy Admin | Повысили семейную версию для доставки общей библиотеки | "
                  f"Android-магазин содержит тот же AAR {tag}, что и клиент. Семейство имеет версию {family[0]} "
                  f"и номер сборки {family[1]} в Android и iOS, включая расширения магазина. | Пользователи Android-магазина "
                  f"получают APK с увеличенным versionCode. Для iOS используйте пакет своей платформы. | "
                  f"Сборочный процесс сверяет собранные идентификаторы и версии обоих семейств. | {source_link} |\n")
    sections = (f"## Ломающие изменения\n\nВ коммите обновления сохранены идентификаторы мобильных пакетов. "
                f"Изменения исходников обвязки приведены в [сравнении ревизий](https://github.com/2dust/AndroidLibXrayLite/compare/{previous_pin}...{pin}).\n\n"
                "## Миграции\n\nИзменение закрепления AAR и номеров приложений не добавляет миграцию базы магазина. "
                "Установка подписанного APK поверх предыдущей версии сохраняет каталог данных приложения.\n\n"
                "## Откат\n\nДля исправляющего выпуска закрепите прежнюю совместимую ревизию, "
                "повысьте номера магазина и клиента и проведите сборки через CI. Перед удалением приложения сохраните "
                "экспорт подписок.\n\n"
                "## Известные ограничения\n\nПроверка установки выполняется на Android-эмуляторе. Проверка на физических "
                "устройствах и наличие подписи Apple требуют отдельных свидетельств.\n\n"
                f"## Чем проверено\n\n[Проверки коммита](https://github.com/booarkz-cpu/shop-by-boo/commit/{source}/checks) "
                "содержат результаты CI. Задания Android проверяют происхождение общего AAR, упаковку и подключение "
                "к тестовому VPN на эмуляторе. Публичные файлы мобильного канала дополнительно проверяются по SHA-256.\n")
    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text()
    new_files = {}
    for key, rows in ((client_tag, client_row), (mobile, family_row + client_row)):
        doc = ROOT / f"docs/releases/{key}.md"
        heading = f"# {key}\n\n"
        if doc.exists() or re.search(rf"^# {re.escape(key)}$", text, re.MULTILINE):
            if not doc.exists() or source_link not in doc.read_text():
                raise ValueError(f"Existing release notes for {key} have a different source")
            if key == mobile:
                validate_mobile(ROOT, key)
            else:
                validate_client(ROOT, client[0])
            continue
        new_files[doc] = heading + table + rows + "\n" + sections
        text = heading + table + rows + "\n" + text
    if new_files:
        write_update({**new_files, changelog: text})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tag")
    p.add_argument("--commit")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--release-notes", action="store_true", help="prepare notes for the just-committed pin and versions")
    mode.add_argument("--check-against", metavar="BASE_SHA", help="verify all versions when the shared pin changes")
    a = p.parse_args(argv)
    if a.check_against:
        try:
            check_against(a.check_against)
            print("Shared Android engine version check passed")
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            p.exit(2, f"{exc}\n")
        return 0
    if not TAG.fullmatch(a.tag or "") or not SHA.fullmatch(a.commit or ""):
        print("bad tag or commit", file=sys.stderr)
        return 2
    script = AAR.read_text()
    old = current_commit(script)
    if a.release_notes:
        try:
            release_notes(a.tag, a.commit)
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            p.exit(2, f"{exc}\n")
        return 0
    if old == a.commit:
        print("up-to-date")
        return 0
    try:
        notices = update_notice(NOTICES.read_text(), old, a.tag, a.commit)
        gradle, version = bump_android(GRADLE.read_text(), 1)
        files = family_update(gradle_version(GRADLE.read_text()), gradle_version(gradle))
        notes = note(NOTES.read_text(), version, a.tag, a.commit)
        build = set_commit(script, a.commit)
    except ValueError as exc:
        p.exit(2, f"{exc}\n")
    if a.write:
        write_update({**files, AAR: build, NOTICES: notices, NOTES: notes, GRADLE: gradle})
    print(f"update {old} {a.commit} {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
