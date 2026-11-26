"""Identify Xcode simulator startup failures eligible for one fresh simulator."""
import argparse
import re
from pathlib import Path


def retry_reason(log: str) -> str | None:
    if re.search(r"\b(?:XCTAssert\w*|XCTFail)\b|test case [^\n]+ (?:started|passed|skipped|failed)\b", log, re.IGNORECASE):
        return None
    ax_timeout = (
        r"XCTDaemonErrorDomain Code=18\b[^\n]*Timed out waiting for AX loaded notification"
        r"|Failed to initialize for UI testing: Error Domain=com\.apple\.dt\.XCTest\.XCTFuture "
        r"Code=1000\b[^\n]*Timed out while loading Accessibility\."
    )
    if re.search(ax_timeout, log):
        return "XCTest timed out waiting for Accessibility before running a test case"
    runner_killed = (
        r"^\s*VpnShopUserUITests-Runner \(\d+\) encountered an error \(Early unexpected exit, "
        r"operation never finished bootstrapping - no restart will be attempted\. "
        r"\(Underlying Error: Test crashed with signal kill before establishing connection\.\)\)\s*$"
    )
    if re.search(runner_killed, log, re.MULTILINE):
        return "the UI test runner was killed before it connected to XCTest"
    if any(message in log for message in ("does not have a process ID", "Failed to launch", "Failed to get background assertion")):
        return "the simulator could not launch the application"
    return None


if __name__ == "__main__":
    from verify_xcuitest_results import summary_allows_startup_retry

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("summary", type=Path, nargs="?")
    args = parser.parse_args()
    if args.summary is not None and not summary_allows_startup_retry(args.summary):
        raise SystemExit("XCUITest summary does not confirm zero test cases")
    reason = retry_reason(args.log.read_text(encoding="utf-8", errors="replace"))
    if reason is None:
        raise SystemExit(1)
    print(reason)
