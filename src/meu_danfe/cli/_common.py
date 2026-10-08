from __future__ import annotations

import logging
import sys

EXIT_OK = 0
EXIT_ARGPARSE = 2
EXIT_PARTIAL_FAILURE = 3
EXIT_CONFIG_ERROR = 4
EXIT_UNEXPECTED = 1


def setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(message)s", stream=sys.stderr)
