"""Weekly ingestion scheduler — the ingest container's long-running CMD.

Runs scripts/ingest_all.main() on a fixed interval (default 7 days) and keeps
running across cycles; a failed cycle is logged and retried on the next tick.
One-shot ingestion is still available via:

    docker compose run --rm ingest uv run python scripts/ingest_all.py
"""

from __future__ import annotations

import os
import time
import traceback

from scripts.ingest_all import main as run_ingest

_INTERVAL_DAYS = float(os.environ.get("INGEST_INTERVAL_DAYS", "7"))


def main() -> None:
    interval = _INTERVAL_DAYS * 86_400
    while True:
        print(f"[scheduler] cycle started at {time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
        try:
            run_ingest()
        except Exception:
            traceback.print_exc()
        print(f"[scheduler] next cycle in {_INTERVAL_DAYS} day(s)", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
