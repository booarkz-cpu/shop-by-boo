"""Render each supported deployment with every combination of its declared profiles."""
from __future__ import annotations

import itertools
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOP_PROFILES = {"mail_receiver": {"mail"}, "backend_standby": {"standby"}}
DEPLOYMENTS = {
    "shop": (["docker-compose.yml"], ".env", SHOP_PROFILES),
    "integration": (["docker-compose.yml", "docker-compose.integration.yml"], ".env", SHOP_PROFILES),
    "local test shop": (["docker-compose.test.yml"], ".env.test", {}),
    "Support Pro": (["services/support-pro/docker-compose.yml"], "services/support-pro/.env", {"clamav": {"antivirus"}}),
}


def services(files: list[str], env_file: str, profiles: tuple[str, ...]) -> dict:
    command = ["docker", "compose", "--env-file", env_file]
    for path in files:
        command.extend(["-f", path])
    for profile in profiles:
        command.extend(["--profile", profile])
    command.extend(["config", "--format", "json"])
    # The normalised model contains interpolated environment variables. Keep it
    # in memory and report only service names when a profile selection differs.
    output = subprocess.check_output(command, cwd=ROOT, env={**os.environ, "COMPOSE_PROFILES": ""})
    return json.loads(output)["services"]


def main() -> None:
    for deployment, (files, env_file, required) in DEPLOYMENTS.items():
        model = services(files, env_file, ("*",))
        members = {name: set(service.get("profiles", [])) for name, service in model.items()}
        for name, expected_profiles in required.items():
            if members.get(name) != expected_profiles:
                raise SystemExit(f"{deployment}: {name} must use profiles {sorted(expected_profiles)}")
        profiles = sorted({profile for group in members.values() for profile in group})
        for size in range(len(profiles) + 1):
            for selected in itertools.combinations(profiles, size):
                expected = {name for name, group in members.items() if not group or group.intersection(selected)}
                actual = set(services(files, env_file, selected))
                label = f"{deployment} [{', '.join(selected) or 'default'}]"
                if expected != actual:
                    raise SystemExit(f"{label}: missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}")
                print(f"{label}: {len(actual)} services")


if __name__ == "__main__":
    main()
