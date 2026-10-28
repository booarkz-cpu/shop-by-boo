#!/usr/bin/env python3
"""Markdown summary of ZAP baseline JSON reports; exits 1 on any High risk alert."""
import json
import sys
from pathlib import Path

RISK = {"3": "High", "2": "Medium", "1": "Low", "0": "Info"}


def main(folder: str) -> int:
    high = 0
    print("### OWASP ZAP baseline\n")
    print("| Цель | Риск | Правило | Срабатываний |\n|---|---|---|---|")
    for report in sorted(Path(folder).glob("*.json")):
        data = json.loads(report.read_text())
        for site in data.get("site", []):
            for alert in site.get("alerts", []):
                risk = RISK.get(str(alert.get("riskcode")), "?")
                high += risk == "High"
                print(f"| {site.get('@name')} | {risk} | {alert.get('alert')} | {alert.get('count', len(alert.get('instances', [])))} |")
    print(f"\nHigh: {high}")
    counts = {k: 0 for k in RISK.values()}
    for report in sorted(Path(folder).glob("*.json")):
        for site in json.loads(report.read_text()).get("site", []):
            for alert in site.get("alerts", []):
                risk = RISK.get(str(alert.get("riskcode")), "Info")
                counts[risk] += 1
                if risk in {"High", "Medium"}:
                    print(f"::warning title=ZAP {risk}::{site.get('@name')}: {alert.get('alert')} "
                          f"({alert.get('count', len(alert.get('instances', [])))})", file=sys.stderr)
    # Annotations go to stderr so the Markdown above stays clean in the step summary.
    print(f"::notice title=OWASP ZAP baseline::High {counts['High']}, Medium {counts['Medium']}, "
          f"Low {counts['Low']}, Info {counts['Info']}", file=sys.stderr)
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "zap"))
