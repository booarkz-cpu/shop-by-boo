"""REQ-INFRA-0008: the installer's stages are written to a machine-readable file — where it is and where it stopped."""
import json
import os
import pathlib
import re
import shutil
import subprocess

from test_production_installer_v2016 import docker_accepting_release_pins

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(tmp_path, body: str) -> tuple[int, dict]:
    status = tmp_path / "install.json"
    script = f"""set -Eeuo pipefail
INSTALL_STATUS={status}
source {ROOT}/infrastructure/deployment/install-status.sh
trap status_on_exit EXIT
die(){{ INSTALL_LAST_ERROR="$*"; exit 1; }}
{body}
"""
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    return proc.returncode, json.loads(status.read_text())


def states(doc):
    return {s["name"]: s["state"] for s in doc["stages"]}


def test_a_finished_install_is_done_stage_by_stage(tmp_path):
    code, doc = run(tmp_path, "status_stage preflight; status_stage settings; status_stage report; status_done")
    assert code == 0 and doc["state"] == "done" and doc["error"] is None
    s = states(doc)
    assert s["preflight"] == s["settings"] == s["report"] == "done" and s["images"] == "pending"
    assert [x["name"] for x in doc["stages"]][:3] == ["preflight", "settings", "dependencies"]
    assert all(x["title"] for x in doc["stages"])


def test_a_failure_names_the_stage_and_the_reason(tmp_path):
    code, doc = run(tmp_path, 'status_stage preflight; status_stage dependencies; die "Поддерживаются Debian/Ubuntu."')
    assert code == 1 and doc["state"] == "failed" and doc["stage"] == "dependencies"
    assert doc["error"] == "Поддерживаются Debian/Ubuntu."
    assert states(doc)["preflight"] == "done" and states(doc)["dependencies"] == "failed"


def test_an_unexpected_error_is_recorded_too(tmp_path):
    code, doc = run(tmp_path, 'status_stage images; false')
    assert code == 1 and doc["state"] == "failed" and doc["stage"] == "images" and doc["error"] == "код выхода 1"


def test_quotes_in_a_message_keep_the_file_valid(tmp_path):
    _, doc = run(tmp_path, 'status_stage files; die "файл \\"x\\" не найден"')
    assert doc["error"] == 'файл "x" не найден'


def test_the_installer_goes_through_every_stage_in_order():
    text = (ROOT / "infrastructure/deployment/install-vps.sh").read_text()
    order = [text.index(f"status_stage {name}\n") for name in
             ("preflight", "settings", "dependencies", "files", "secrets", "firewall", "images", "services", "health", "admin", "report")]
    assert order == sorted(order)
    assert text.rstrip().endswith('status_done\nrm -f "$RESUME_FILE"') and "trap status_on_exit EXIT" in text


def test_a_stopped_installation_continues_from_where_it_stopped(tmp_path):
    """v28.145.0 (owner's decision of 2026-11-14): a second run after a failure goes on, it does not refuse."""
    text = (ROOT / "infrastructure/deployment/install-vps.sh").read_text()
    resume = text.index("if (( RESUME )); then")
    block_end = text.index('done > "$RESUME_FILE" )\nfi\n')
    # The questions, packages, files and secrets are inside the block a continued run skips; the firewall and later are not.
    for marker in ("status_stage settings", "prompt_required BASE_DOMAIN", "status_stage dependencies", "status_stage files",
                   "status_stage secrets", "} > .env"):
        assert resume < text.index(marker) < block_end, marker
    assert block_end < text.index("status_stage firewall")
    # A resumed run gets its answers from the saved file and image names from the release.
    saved = set(re.search(r"for name in ([A-Z_ \\\n]+); do", text[block_end - 600:block_end]).group(1).split()) - {"\\"}
    later = text[block_end:]
    before_pins, after_pins = later.split("\n. ./.env.images\n", 1)
    pin_start = before_pins.index("bash scripts/pin-images.sh")
    assert before_pins.index("status_stage images") < pin_start
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    shutil.copyfile(ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    docker_accepting_release_pins(fakebin)
    load_pins = before_pins[pin_start:] + '\n. ./.env.images\nprintf "%s\\n" "$NODE_BASE_IMAGE"'
    result = subprocess.run(
        ["bash", "-eu", "-c", load_pins], cwd=tmp_path, capture_output=True, text=True, check=True,
        env={**os.environ, "APP_DIR": str(tmp_path), "PATH": f"{fakebin}:{os.environ['PATH']}",
             "NODE_BASE_IMAGE": "stale-image-from-previous-run"},
    )
    pins = dict(line.split("=", 1) for line in (tmp_path / ".env.images").read_text().splitlines())
    assert result.stdout.splitlines()[-1] == pins["NODE_BASE_IMAGE"]
    assert re.fullmatch(r"node:[^@]+@sha256:[a-f0-9]{64}", pins["NODE_BASE_IMAGE"])
    available = saved | {"ROOT", "INSTALL_STATUS", "INSTALLER_VERSION", "RESUME_FILE", "SSH_CONNECTION"}
    for section, inputs in ((before_pins, set()), (after_pins, pins.keys())):
        available.update(inputs)
        available.update(re.findall(r"^\s*([A-Z][A-Z0-9_]*)=", section, re.M))
        used = set(re.findall(r"\$\{?([A-Z][A-Z0-9_]*)", section))
        assert used <= available, used - available
    # A copy that stopped before .env is removed only when the previous run did not finish.
    assert '"state":"failed"' in text and '! -e "$ROOT/.env"' in text and 'rm -rf "$ROOT"' in text


def test_resume_marks_the_finished_stages(tmp_path):
    code, doc = run(tmp_path, "status_resume_from secrets; status_stage firewall; status_done")
    s = states(doc)
    assert code == 0 and all(s[n] == "done" for n in ("preflight", "settings", "dependencies", "files", "secrets", "firewall"))
    assert s["images"] == "pending"
