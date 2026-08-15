"""Leg A — words out. Whisper via OpenRouter's OpenAI-compatible endpoint."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path

import httpx

from .config import Config
from .openrouter import request_json

log = logging.getLogger(__name__)

NO_AUDIO = "(no audio)"


async def transcribe(audio: Path | None, client: httpx.AsyncClient, config: Config) -> str:
    """Transcribe an audio file. A silent clip is a success, not a failure."""
    if audio is None:
        return NO_AUDIO

    mime = mimetypes.guess_type(audio.name)[0] or "audio/mpeg"
    payload = await request_json(
        client,
        config,
        "POST",
        "/audio/transcriptions",
        timeout=config.audio_timeout,
        files={"file": (audio.name, audio.read_bytes(), mime)},
        data={"model": config.transcription_model, "response_format": "json"},
    )

    text = (payload.get("text") or "").strip()
    if not text:
        return NO_AUDIO
    return text
