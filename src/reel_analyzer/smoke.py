"""The dev loop: run the exact pipeline the MCP tool runs, outside MCP.

    python -m reel_analyzer.smoke <url_or_path>

Exits non-zero only when both legs fail.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from .acquire import AcquisitionError
from .config import ConfigError, load_config
from .pipeline import AnalysisError, analyze


async def run(target: str, verbose: bool) -> int:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    print(f"model: vision={config.vision_model} transcription={config.transcription_model}", file=sys.stderr)
    print(f"feed mode: {config.feed_mode}", file=sys.stderr)

    started = time.monotonic()
    try:
        output = await analyze(target, config)
    except (AnalysisError, AcquisitionError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(output)
    print(f"\n[{elapsed:.1f}s]", file=sys.stderr)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="reel-analyzer-smoke", description=__doc__)
    parser.add_argument("target", help="video URL or local file path")
    parser.add_argument("-v", "--verbose", action="store_true", help="log pipeline progress")
    args = parser.parse_args()

    sys.exit(asyncio.run(run(args.target, args.verbose)))


if __name__ == "__main__":
    main()
