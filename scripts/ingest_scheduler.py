"""Scheduled ingestion loop — the ingest container's long-running CMD.

Runs scripts/ingest_all.main() at fixed times of day (default 11:00 and
19:00 KST) and keeps running across cycles; a failed cycle is logged and
retried on the next slot. One-shot ingestion is still available via:

    docker compose run --rm ingest uv run python scripts/ingest_all.py
"""

from __future__ import annotations

import os
import time
import traceback
from datetime import datetime, timedelta

from scripts.ingest_all import main as run_ingest

# Comma-separated 24h "HH:MM" slots, e.g. "11:00,19:00".
_SLOTS = os.environ.get("INGEST_TIMES", "11:00,19:00")


def _parse_slots(raw: str) -> list[timedelta]:
    slots: list[timedelta] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hour_s, minute_s = part.split(":")
        slots.append(timedelta(hours=int(hour_s), minutes=int(minute_s)))
    return sorted(slots)


def _seconds_until_next(slots: list[timedelta], now: datetime) -> float:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    upcoming = [today + slot for slot in slots if today + slot > now]
    target = upcoming[0] if upcoming else today + slots[0] + timedelta(days=1)
    return (target - now).total_seconds()


def main() -> None:
    slots = _parse_slots(_SLOTS)
    rendered = ", ".join(str(slot) for slot in slots)
    print(f"[scheduler] ingest slots: {rendered} (local time)", flush=True)
    while True:
        wait = _seconds_until_next(slots, datetime.now())
        print(
            f"[scheduler] next cycle in {wait / 3600:.1f}h "
            f"at {datetime.now() + timedelta(seconds=wait):%H:%M}",
            flush=True,
        )
        time.sleep(max(wait, 1))
        print(f"[scheduler] cycle started at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        try:
            run_ingest()
        except Exception:
            traceback.print_exc()


if __name__ == "__main__":
    main()
