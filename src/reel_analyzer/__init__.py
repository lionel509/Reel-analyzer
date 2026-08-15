"""reel-analyzer — an MCP server that watches a video so the calling model doesn't have to.

One tool, `analyze_video(url_or_path)`, returns a plain-text block with a TRANSCRIPT
section (Whisper) and a VISUAL DESCRIPTION section (a vision model reading extracted
frames). The two legs run in parallel and fail independently.
"""

__version__ = "0.1.0"
