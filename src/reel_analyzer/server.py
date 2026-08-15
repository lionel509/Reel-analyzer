"""The MCP server. One tool, registered FastMCP-style, spoken over stdio."""

from __future__ import annotations

import logging
import sys

from mcp.server.mcpserver import MCPServer

from .acquire import AcquisitionError
from .config import ConfigError
from .pipeline import AnalysisError, analyze

# stdio carries the protocol, so every log line must go to stderr.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

mcp = MCPServer("reel-analyzer")


@mcp.tool()
async def analyze_video(url_or_path: str) -> str:
    """Watch a video and return what is said and what is shown.

    Accepts an Instagram Reel, TikTok, YouTube, or any other yt-dlp-supported URL,
    or a path to a local video file. Returns a plain-text block with a TRANSCRIPT
    section (spoken audio) and a VISUAL DESCRIPTION section (on-screen action plus
    every caption and overlay, transcribed verbatim).

    Silent videos are normal: the transcript reads "(no audio)" and the visual
    description carries the content. If one half fails the other is still returned.

    Args:
        url_or_path: The video URL, or an absolute path to a local video file.
    """
    try:
        return await analyze(url_or_path)
    except (AnalysisError, AcquisitionError, ConfigError) as exc:
        # Readable sentences, not stack traces — the calling model relays these.
        raise RuntimeError(str(exc)) from exc


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
