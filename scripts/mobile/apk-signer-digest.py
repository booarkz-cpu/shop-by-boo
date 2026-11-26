"""Read the unique APK signing certificate from a verified apksigner report."""
import re
import sys


def signer_digest(report: str) -> str:
    if re.findall(r"^Number of signers: (.+)$", report, re.MULTILINE) != ["1"]:
        raise ValueError("Expected one APK signer")
    # Build Tools 35/36 label the signer by index. Build Tools 37 label it by scheme.
    # Several verified schemes can report the same signing certificate.
    labels = r"(?:Signer #\d+|V\d+(?:\.\d+)* Signer(?: #\d+)?:)"
    entries = re.findall(rf"^{labels} certificate SHA-256 digest: (.*)$", report, re.MULTILINE)
    digests = {value.lower() for value in entries}
    if len(digests) != 1:
        raise ValueError("Expected exactly one APK signing certificate SHA-256 digest")
    digest = digests.pop()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid APK signing certificate SHA-256 digest")
    return digest


if __name__ == "__main__":
    try:
        print(signer_digest(sys.stdin.read()))
    except ValueError as exc:
        sys.exit(str(exc))
