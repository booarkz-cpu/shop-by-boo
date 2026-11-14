"""REQ-INFRA-0008: the installer's stages are written to a machine-readable file — where it is and where it stopped."""
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def run(tmp_path, body: str) -> tuple[int, dict]:
    status = tmp_path / "install.json"
    script = f"""set -Eeuo pipefail
INSTALL_STATUS={status}
source {ROOT}/deploy/install-status.sh
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
    text = (ROOT / "deploy/install-vps.sh").read_text()
    order = [text.index(f"status_stage {name}\n") for name in
             ("preflight", "settings", "dependencies", "files", "secrets", "firewall", "images", "services", "health", "admin", "report")]
    assert order == sorted(order)
    assert text.rstrip().endswith("status_done") and "trap status_on_exit EXIT" in text
