"""Weekly source ingestion worker — entrypoint placeholder.

Real ingestion logic lands in issues #3–#12. This module only provides a
runnable entrypoint so the skeleton boots and can be smoke-tested.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    logging.info("ingest worker skeleton — no sources configured yet")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
