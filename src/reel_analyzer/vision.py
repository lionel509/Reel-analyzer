"""Leg B — watch it. A vision model reads extracted frames (or the raw clip).

This leg never transcribes speech; that is Leg A's job. It reports what is on
screen and reads on-screen text verbatim, which is the entire answer when the
clip is silent and carries its meaning in captions.

Long or fast-cut reels produce more frames than fit in one request, so frames
are sent in chunks that run concurrently and are stitched back together in
time order. Density is never silently traded away for a single round trip.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

import httpx

from .acquire import Frame
from .config import Config
from .format import format_duration
from .openrouter import OpenRouterError, request_json

log = logging.getLogger(__name__)

PROMPT = """You are watching {scope} of a short-form video. You will be shown frames sampled at every scene change plus a steady interval, in chronological order.

Report two things:

1. WHAT HAPPENS — the action on screen, the setting, who or what is visible, and how the shots change over time. Note hard cuts and shifts in scene.
2. ON-SCREEN TEXT — every caption, overlay, title card, watermark, and piece of readable text, transcribed VERBATIM in the order it appears. Do not paraphrase, summarise, or correct spelling. If text is partially cut off, transcribe what is legible and mark the rest [unclear].

Do not transcribe spoken audio — you cannot hear it, and it is handled separately. Do not speculate about what is said.

Write in plain prose. Be specific and complete rather than brief; if the video is silent, your description is the only record of its content."""

WHOLE_CLIP = "the whole"
VIDEO_PROMPT = PROMPT.format(scope=WHOLE_CLIP).replace(
    "You will be shown frames sampled at every scene change plus a steady interval, in chronological order.",
    "You will be shown the clip itself.",
)


def _data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _scope(frames: list[Frame], total_chunks: int, index: int) -> str:
    if total_chunks == 1:
        return WHOLE_CLIP
    start = format_duration(frames[0].timestamp) or "0:00"
    end = format_duration(frames[-1].timestamp) or "the end"
    return f"part {index + 1} of {total_chunks} ({start} to {end})"


def _build_content(frames: list[Frame], video: Path | None, prompt: str) -> list[dict]:
    if video is not None:
        return [
            {"type": "text", "text": prompt},
            {"type": "video_url", "video_url": {"url": _data_url(video, "video/mp4")}},
        ]

    content: list[dict] = [{"type": "text", "text": prompt}]
    for frame in frames:
        content.append(
            {"type": "image_url", "image_url": {"url": _data_url(frame.path, "image/jpeg")}}
        )
    return content


async def _describe_chunk(
    frames: list[Frame],
    client: httpx.AsyncClient,
    config: Config,
    prompt: str,
    *,
    video: Path | None = None,
) -> str:
    payload = await request_json(
        client,
        config,
        "POST",
        "/chat/completions",
        timeout=config.vision_timeout,
        json={
            "model": config.vision_model,
            "messages": [
                {"role": "user", "content": _build_content(frames, video, prompt)}
            ],
        },
    )

    choices = payload.get("choices") or []
    if not choices:
        raise OpenRouterError(f"{config.vision_model} returned no choices")

    text = (choices[0].get("message", {}).get("content") or "").strip()
    if not text:
        raise OpenRouterError(f"{config.vision_model} returned an empty description")
    return text


async def describe(
    frames: list[Frame],
    client: httpx.AsyncClient,
    config: Config,
    *,
    video: Path | None = None,
) -> str:
    """Describe the clip. Chunks are sent concurrently and stitched in time order."""
    if video is not None:
        return await _describe_chunk([], client, config, VIDEO_PROMPT, video=video)

    size = max(1, config.vision_chunk_size)
    chunks = [frames[i : i + size] for i in range(0, len(frames), size)]

    if len(chunks) == 1:
        return await _describe_chunk(chunks[0], client, config, PROMPT.format(scope=WHOLE_CLIP))

    log.info("describing %d frames across %d chunks of up to %d", len(frames), len(chunks), size)

    results = await asyncio.gather(
        *(
            _describe_chunk(chunk, client, config, PROMPT.format(scope=_scope(chunk, len(chunks), i)))
            for i, chunk in enumerate(chunks)
        ),
        return_exceptions=True,
    )

    sections: list[str] = []
    failures = 0
    for index, (chunk, result) in enumerate(zip(chunks, results)):
        start = format_duration(chunk[0].timestamp) or "0:00"
        end = format_duration(chunk[-1].timestamp) or "end"
        if isinstance(result, BaseException):
            failures += 1
            sections.append(f"[{start}–{end}] (this section failed: {result})")
        else:
            sections.append(f"[{start}–{end}]\n{result}")

    if failures == len(chunks):
        raise OpenRouterError(f"every section failed; last error: {results[-1]}")

    return "\n\n".join(sections)
