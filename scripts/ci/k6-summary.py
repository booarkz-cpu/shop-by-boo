#!/usr/bin/env python3
"""Print the main k6 numbers (p95 per scenario, failure rate, checks, requests) as a GitHub notice."""
import json
import sys


def main(path: str) -> None:
    metrics = json.load(open(path)).get("metrics", {})
    parts = []
    for name, metric in sorted(metrics.items()):
        if name.startswith("http_req_duration{scenario:"):
            parts.append(f"{name.split(':', 1)[1].rstrip('}')} p95 {metric.get('p(95)', 0):.0f} ms")
    failed = metrics.get("http_req_failed", {}).get("value", 0)
    checks = metrics.get("checks", {}).get("value", 0)
    reqs = metrics.get("http_reqs", {})
    parts += [f"failed {failed * 100:.2f} %", f"checks {checks * 100:.1f} %",
              f"{reqs.get('count', 0)} requests, {reqs.get('rate', 0):.1f}/s"]
    print("::notice title=k6 load profile::" + "; ".join(parts))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "k6-summary.json")
