"""Fixed-evaluation-set harness (issue #23).

Runs the versioned cases in tests/eval/evalset.json against a live API
(SEARCH_API_BASE, default http://localhost:8000) and reports per-case
pass/fail with the overall agreement rate. Exit code 1 when any case fails.

Usage:
    uv run python tests/eval/run_eval.py [--api http://localhost:8000]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

EVALSET = Path(__file__).parent / "evalset.json"


def search(base: str, profile: dict[str, Any], page_size: int = 50) -> dict[str, Any]:
    payload = json.dumps({**profile, "page_size": page_size}).encode()
    req = urllib.request.Request(
        f"{base}/v1/search",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        body: dict[str, Any] = json.loads(res.read())
        return body


def check_case(case: dict[str, Any], base: str) -> tuple[bool, list[str]]:
    failures: list[str] = []
    profile = case["profile"]
    expect = case["expect"]
    data = search(base, profile)
    results = data["results"]
    statuses = Counter(r["status"] for r in results)

    if data["total"] < expect.get("total_min", 0):
        failures.append(f"total {data['total']} < {expect['total_min']}")
    if statuses.get("ineligible", 0) < expect.get("ineligible_min", 0):
        failures.append(f"ineligible {statuses.get('ineligible', 0)} < {expect['ineligible_min']}")
    if statuses.get("eligible", 0) > expect.get("eligible_max", 10**9):
        failures.append(f"eligible {statuses.get('eligible', 0)} > {expect['eligible_max']}")

    ratio = statuses.get("ineligible", 0) / max(len(results), 1)
    if ratio > expect.get("max_ineligible_ratio", 1.0):
        failures.append(f"ineligible ratio {ratio:.2f} exceeds bound")

    for anchor in expect.get("anchored_verdicts", []):
        needle = anchor["title_contains"]
        match = next((r for r in results if needle in r["policy_title"]), None)
        if match is None:
            failures.append(f"anchor '{needle}' not found in results")
        elif match["status"] != anchor["status"]:
            failures.append(f"anchor '{needle}': {match['status']} != {anchor['status']}")

    if expect.get("all_have_deadline_or_null"):
        for r in results:
            if r["application_deadline"] is None:
                continue
            if not _is_iso_date(r["application_deadline"]):
                failures.append(f"malformed deadline on '{r['policy_title'][:30]}'")
                break

    if expect.get("all_have_topic"):
        missing = [r["policy_title"][:30] for r in results if not r.get("topic")]
        if missing:
            failures.append(f"missing topic on {missing[:3]}")

    if expect.get("no_business_category") and any(r["category"] == "business" for r in results):
        failures.append("business announcement leaked into individual search")

    if expect.get("includes_business_category") and not any(
        r["category"] == "business" for r in results
    ):
        failures.append("business owner search has no business announcements")

    if expect.get("all_deadlines_not_past"):
        today = date.today().isoformat()
        past = [r["policy_title"][:30] for r in results
                if r["application_deadline"] and r["application_deadline"] < today]
        if past:
            failures.append(f"expired announcements surfaced: {past[:3]}")

    return (not failures), failures


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def main() -> None:
    base = "http://localhost:8000"
    if "--api" in sys.argv:
        base = sys.argv[sys.argv.index("--api") + 1]

    cases = json.loads(EVALSET.read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    passed = 0
    for case in cases:
        ok, failures = check_case(case, base)

        if "results_differ_from" in case.get("expect", {}):
            other = search(base, by_id[case["expect"]["results_differ_from"]]["profile"])
            mine = search(base, case["profile"])
            if _verdict_sig(mine) == _verdict_sig(other):
                ok = False
                failures.append("verdicts identical to reference case (employment had no effect)")

        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {case['id']} — {case['name']}")
        for f in failures:
            print(f"       · {f}")
        passed += ok

    print(f"\nAgreement: {passed}/{len(cases)} ({passed / len(cases):.0%})")
    sys.exit(0 if passed == len(cases) else 1)


def _verdict_sig(data: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted((r["policy_title"], r["status"]) for r in data["results"])


if __name__ == "__main__":
    main()
