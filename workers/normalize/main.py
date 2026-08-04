"""Policy and eligibility normalization worker — entrypoint placeholder.

Real normalization logic lands in issue #15. This module only provides a
runnable entrypoint so the skeleton boots and can be smoke-tested.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    logging.info("normalize worker skeleton — no rules configured yet")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
