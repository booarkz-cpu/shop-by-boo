"""Exercise Support Pro uploads against the native scanner with a private test signature."""
import asyncio
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services/support-pro"))
from app.storage import scan_file

MARKER = b"CorgiLucy scanner integration fixture"


def fixtures(directory: Path) -> None:
    directory.chmod(0o755)
    signatures = directory / "signatures"
    signatures.mkdir(mode=0o755)
    (signatures / "test.ndb").write_text(f"Lucy.Integration:0:*:{MARKER.hex()}\n")
    (directory / "clamd.conf").write_text(
        "DatabaseDirectory /mnt/signatures\nTCPSocket 3310\nTCPAddr 0.0.0.0\n"
        "PidFile /tmp/clamd.pid\nForeground yes\n"
    )
    (directory / "clean.txt").write_bytes(b"ordinary support attachment\n")
    (directory / "marker.txt").write_bytes(MARKER)
    for path in (signatures / "test.ndb", directory / "clamd.conf"):
        path.chmod(0o644)


def verify(directory: Path, port: int) -> None:
    os.environ.update(CLAMAV_HOST="127.0.0.1", CLAMAV_PORT=str(port), REQUIRE_ANTIVIRUS="true")
    deadline = time.monotonic() + 60
    last_response = "waiting for the scanner"
    while True:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                connection.sendall(b"zPING\0")
                with connection.makefile("rb") as stream:
                    response = stream.read(5)
                    if response == b"PONG\0":
                        break
                    last_response = f"Received {response!r}"
        except OSError as error:
            last_response = str(error)
        if time.monotonic() >= deadline:
            raise RuntimeError(f"ClamAV did not respond to PING: {last_response}")
        time.sleep(1)
    asyncio.run(scan_file(directory / "clean.txt"))
    try:
        asyncio.run(scan_file(directory / "marker.txt"))
    except ValueError as exc:
        if str(exc) != "Файл отклонён антивирусом":
            raise
    else:
        raise RuntimeError("Support Pro accepted the test signature")


def main(image: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        fixtures(directory)
        container = subprocess.check_output([
            "docker", "run", "--detach", "--rm", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--user", "clamav", "--tmpfs", "/tmp:mode=1777",
            "--publish", "127.0.0.1::3310", "--volume", f"{directory}:/mnt:ro",
            "--entrypoint", "clamd", image, "--config-file=/mnt/clamd.conf",
        ], text=True).strip()
        try:
            arch = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Architecture}}", image], text=True).strip()
            expected = {"x86_64": "amd64", "aarch64": "arm64"}[platform.machine()]
            if arch != expected:
                raise RuntimeError(f"Expected native {expected}, received {arch}")
            endpoint = subprocess.check_output(["docker", "port", container, "3310/tcp"], text=True).strip()
            host, port = endpoint.rsplit(":", 1)
            if host != "127.0.0.1":
                raise RuntimeError("The test scanner must listen only on loopback")
            verify(directory, int(port))
        except Exception:
            subprocess.run(["docker", "logs", "--tail", "20", container], check=False)
            raise
        finally:
            subprocess.run(["docker", "rm", "--force", container], check=False)
    print("Support Pro accepted a clean upload and rejected the private test marker")


if __name__ == "__main__":
    main(sys.argv[1])
