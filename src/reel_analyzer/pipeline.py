"""Orchestration: acquire once, then run both legs in parallel and join the results."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

import httpx

from .acquire import AcquisitionError, extract_audio, extract_frames, fetch_video, probe, require_ffmpeg
from .config import Config, load_config
from .format import MediaInfo, render
from .transcribe import transcribe
from .vision import describe

log = logging.getLogger(__name__)


class AnalysisError(RuntimeError):
    """Both legs failed. The only hard-error case."""


async def analyze(url_or_path: str, config: Config | None = None) -> str:
    """Run the full pipeline and return the formatted two-section block."""
    config = config or load_config()
    require_ffmpeg()

    target = url_or_path.strip()
    if not target:
        raise AnalysisError("no URL or file path was provided")

    notes: list[str] = []

    with tempfile.TemporaryDirectory(prefix="reel-analyzer-") as tmp:
        workdir = Path(tmp)

        # Probe is best-effort: a missing title should never sink the run.
        try:
            info = await probe(target, config)
        except AcquisitionError as exc:
            log.info("probe failed (%s); continuing without metadata", exc)
            info = MediaInfo()

        if info.duration and info.duration > config.max_duration:
            raise AnalysisError(
                f"video is {info.duration / 60:.1f} minutes, over the "
                f"{config.max_duration / 60:.0f}-minute limit (raise MAX_DURATION_SECONDS to allow it)"
            )

        try:
            video = await fetch_video(target, workdir, config)
        except AcquisitionError as exc:
            raise AnalysisError(str(exc)) from exc

        async with httpx.AsyncClient() as client:
            transcript, visual = await asyncio.gather(
                _leg_a(video, workdir, client, config),
                _leg_b(video, workdir, client, config, info.duration, notes),
                return_exceptions=True,
            )

    transcript_failed = isinstance(transcript, BaseException)
    visual_failed = isinstance(visual, BaseException)

    if transcript_failed and visual_failed:
        raise AnalysisError(
            f"both legs failed — transcription: {transcript}; visual analysis: {visual}"
        )

    transcript_text = (
        f"(transcription failed: {transcript})" if transcript_failed else str(transcript)
    )
    visual_text = f"(visual analysis failed: {visual})" if visual_failed else str(visual)

    return render(info, transcript_text, visual_text, notes)


async def _leg_a(
    video: Path, workdir: Path, client: httpx.AsyncClient, config: Config
) -> str:
    audio = await extract_audio(video, workdir)
    return await transcribe(audio, client, config)


async def _leg_b(
    video: Path,
    workdir: Path,
    client: httpx.AsyncClient,
    config: Config,
    duration: float | None,
    notes: list[str],
) -> str:
    if not config.uses_frames:
        return await describe([], client, config, video=video)

    frames, frame_notes = await extract_frames(video, workdir, config, duration)
    notes.extend(frame_notes)
    return await describe(frames, client, config)
