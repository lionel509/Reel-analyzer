"""Environment-driven configuration, loaded once and passed down explicitly."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

try:  # optional dev convenience, never required at runtime
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# openai/whisper-1 and openai/gpt-4o-mini-transcribe both return 403 on OpenRouter
# (verified 2026-08-02); whisper-large-v3 is the one that actually serves.
DEFAULT_TRANSCRIPTION_MODEL = "openai/whisper-large-v3"
DEFAULT_VISION_MODEL = "google/gemma-4-26b-a4b-it"

# One settings file, read by every host. Beats pasting the key into each host's
# env block: set it once with `reel-analyzer-configure`, and Cherry Studio,
# Obsidian, and Claude Code all pick it up.
DEFAULT_SETTINGS_PATH = Path.home() / ".config" / "reel-analyzer" / "config.json"


class ConfigError(RuntimeError):
    """Configuration is missing or unusable. Surfaced to the caller verbatim."""


def settings_path() -> Path:
    override = os.environ.get("REEL_ANALYZER_CONFIG", "").strip()
    return Path(override).expanduser() if override else DEFAULT_SETTINGS_PATH


def read_settings_file() -> dict[str, object]:
    """Load the settings file. A missing file is normal; a corrupt one is not."""
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def write_settings_file(values: dict[str, object]) -> Path:
    """Merge values into the settings file, keeping it owner-readable only."""
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = {**read_settings_file(), **{k: v for k, v in values.items() if v not in (None, "")}}
    path.write_text(json.dumps(merged, indent=2) + "\n")
    path.chmod(0o600)  # it holds an API key
    return path


class _Settings:
    """Resolves a setting from the environment first, then the settings file.

    Environment wins so a host can override per-server without editing the file.
    """

    def __init__(self, file_values: dict[str, object]) -> None:
        self._file = file_values

    def raw(self, name: str) -> str:
        value = os.environ.get(name, "").strip()
        if value:
            return value
        from_file = self._file.get(name)
        return "" if from_file is None else str(from_file).strip()

    def text(self, name: str, default: str) -> str:
        return self.raw(name) or default

    def number(self, name: str, default: float) -> float:
        raw = self.raw(name)
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"{name} must be a number, got {raw!r}") from exc

    def integer(self, name: str, default: int) -> int:
        raw = self.raw(name)
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    api_key: str
    transcription_model: str
    vision_model: str

    # "frames" = extract our own frames (default, denser).
    # "video"  = send the whole clip as one base64 video part (model samples ~1fps).
    feed_mode: str

    instagram_cookies: Path | None

    # Frame sampling knobs — see the Media Acquisition note.
    scene_threshold: float
    uniform_fps: float
    frame_min_gap: float
    max_frames: int
    vision_chunk_size: int
    frame_long_edge: int
    frame_quality: int

    max_duration: float
    audio_timeout: float
    vision_timeout: float
    download_timeout: float
    max_retries: int

    referer: str
    app_title: str

    @property
    def uses_frames(self) -> bool:
        return self.feed_mode == "frames"


def load_config(*, require_key: bool = True) -> Config:
    """Read configuration from the environment.

    `require_key=False` lets tooling introspect settings without an API key present.
    """
    if load_dotenv is not None:
        load_dotenv()

    settings = _Settings(read_settings_file())

    api_key = settings.raw("OPENROUTER_API_KEY")
    if require_key and not api_key:
        raise ConfigError(
            "No OpenRouter API key found. Run `reel-analyzer-configure` to save one to "
            f"{settings_path()}, or set OPENROUTER_API_KEY in the environment."
        )

    feed_mode = settings.text("FEED_MODE", "frames").lower()
    if feed_mode not in {"frames", "video"}:
        raise ConfigError(f"FEED_MODE must be 'frames' or 'video', got {feed_mode!r}")

    cookies_raw = settings.raw("INSTAGRAM_COOKIES_FILE")
    cookies: Path | None = None
    if cookies_raw:
        cookies = Path(cookies_raw).expanduser()
        if not cookies.is_file():
            raise ConfigError(f"INSTAGRAM_COOKIES_FILE points at a missing file: {cookies}")

    return Config(
        api_key=api_key,
        transcription_model=settings.text("TRANSCRIPTION_MODEL", DEFAULT_TRANSCRIPTION_MODEL),
        vision_model=settings.text("VISION_MODEL", DEFAULT_VISION_MODEL),
        feed_mode=feed_mode,
        instagram_cookies=cookies,
        # 3fps beats the ~1fps a native-video model would sample at, and survives
        # the cap up to a minute. Measured 2026-08-02: no images-per-request limit
        # beyond the 262k context window, ~266 tokens per 768px frame, so 150
        # frames in one call costs $0.006. Density was never the expensive part.
        scene_threshold=settings.number("SCENE_THRESHOLD", 0.3),
        uniform_fps=settings.number("UNIFORM_FPS", 3.0),
        # Must stay below the uniform step (1/fps) or it would drop every other
        # uniform tick. At 3fps the step is 0.333s.
        frame_min_gap=settings.number("FRAME_MIN_GAP", 0.15),
        max_frames=settings.integer("MAX_FRAMES", 360),
        vision_chunk_size=settings.integer("VISION_CHUNK_SIZE", 120),
        frame_long_edge=settings.integer("FRAME_LONG_EDGE", 768),
        frame_quality=settings.integer("FRAME_QUALITY", 3),
        max_duration=settings.number("MAX_DURATION_SECONDS", 900.0),
        audio_timeout=settings.number("AUDIO_TIMEOUT", 120.0),
        vision_timeout=settings.number("VISION_TIMEOUT", 240.0),
        download_timeout=settings.number("DOWNLOAD_TIMEOUT", 300.0),
        max_retries=settings.integer("MAX_RETRIES", 4),
        referer=settings.text("OPENROUTER_REFERER", "https://github.com/lionel509/Reel-analyzer"),
        app_title=settings.text("OPENROUTER_TITLE", "reel-analyzer"),
    )
