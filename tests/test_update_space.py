"""REQ-INFRA-0011: an update is cancelled before anything is written when the disk cannot hold it."""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sh(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", f"source {ROOT}/scripts/update-space.sh; {code}"], capture_output=True, text=True)


def test_need_counts_snapshot_dump_and_reserve():
    assert sh("space_need_kb 1000 500").stdout.strip() == str(1000 + 1000 + 2097152)
    assert sh("SPACE_RESERVE_KB=0; space_need_kb 0 0").stdout.strip() == "0"


def test_too_little_space_stops_with_both_numbers():
    low = sh("space_check 4194304 1048576")
    assert low.returncode == 1
    assert "нужно 4096 МБ, свободно 1024 МБ" in low.stderr and "ничего не изменено" in low.stderr
    assert sh("space_check 1024 2048").returncode == 0


def test_update_checks_space_before_the_snapshot():
    text = (ROOT / "scripts/update.sh").read_text()
    assert text.index("space_check") < text.index('SNAPSHOT="$ROLLBACK_DIR') < text.index("tar --exclude")
    assert "|| exit 3" in text
