"""Media acquisition: probe, download, audio extraction, frame sampling.

The AI half of this project is the easy half. This module is where it breaks, so
every failure here is translated into a sentence a human can act on.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .format import MediaInfo

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    """One sampled frame, with the timestamp it was taken from."""

    timestamp: float
    path: Path

_PTS_TIME = re.compile(r"pts_time:([0-9.]+)")

# yt-dlp error text -> what the user should actually do about it.
_ERROR_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"login required|rate-?limit reached|requested content is not available", re.I),
        "this reel requires login cookies — set INSTAGRAM_COOKIES_FILE to a Netscape-format "
        "cookies export from a logged-in browser session",
    ),
    (
        re.compile(r"429|too many requests|rate.?limit", re.I),
        "the platform rate-limited this request — try again shortly",
    ),
    (
        re.compile(r"private|not authorized|sign in to confirm", re.I),
        "this video is private or age-gated — set INSTAGRAM_COOKIES_FILE (or the equivalent "
        "cookies file for the platform) to access it",
    ),
    (
        re.compile(r"unsupported url|is not a valid url", re.I),
        "yt-dlp does not recognise that URL",
    ),
    (
        re.compile(r"video unavailable|has been removed|404", re.I),
        "that video is unavailable or has been removed",
    ),
)


class AcquisitionError(RuntimeError):
    """Media could not be obtained. The message is safe to show the caller."""


def _humanise(error: Exception) -> str:
    text = str(error)
    for pattern, hint in _ERROR_HINTS:
        if pattern.search(text):
            return hint
    # Strip yt-dlp's "ERROR: [extractor] id:" prefix noise.
    cleaned = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?", "", text).strip()
    return cleaned[:300] or "media download failed"


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise AcquisitionError(
            "ffmpeg and ffprobe must be installed and on PATH (macOS: `brew install ffmpeg`)"
        )


async def _run(*args: str, timeout: float = 120.0) -> tuple[int, str]:
    """Run a subprocess, returning (returncode, combined stderr+stdout tail)."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise AcquisitionError(f"`{args[0]}` timed out after {timeout:.0f}s") from None

    output = (stderr or b"").decode("utf-8", "replace") + (stdout or b"").decode("utf-8", "replace")
    return process.returncode or 0, output


def _ydl_opts(config: Config, outtmpl: str) -> dict:
    opts: dict = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        # Prefer a single progressive mp4 so we never need a merge step.
        "format": "best[ext=mp4]/bv*+ba/best",
        "merge_output_format": "mp4",
        "retries": 3,
        "socket_timeout": 30,
    }
    if config.instagram_cookies is not None:
        opts["cookiefile"] = str(config.instagram_cookies)
    return opts


async def probe(url_or_path: str, config: Config) -> MediaInfo:
    """Fetch title / platform / duration without downloading the media."""
    path = Path(url_or_path).expanduser()
    if path.is_file():
        duration = await _probe_duration(path)
        return MediaInfo(title=path.name, platform="file", duration=duration)

    from yt_dlp import YoutubeDL

    def _extract() -> dict:
        with YoutubeDL({**_ydl_opts(config, "-"), "skip_download": True}) as ydl:
            return ydl.extract_info(url_or_path, download=False)

    try:
        info = await asyncio.to_thread(_extract)
    except Exception as exc:  # yt-dlp raises a wide range of extractor errors
        raise AcquisitionError(_humanise(exc)) from exc

    duration = info.get("duration")
    return MediaInfo(
        title=info.get("title") or None,
        platform=(info.get("extractor_key") or info.get("extractor") or "").lower() or None,
        duration=float(duration) if duration else None,
    )


async def _probe_duration(path: Path) -> float | None:
    code, output = await _run(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        timeout=30,
    )
    if code != 0:
        return None
    try:
        return float(output.strip().splitlines()[0])
    except (ValueError, IndexError):
        return None


async def fetch_video(url_or_path: str, workdir: Path, config: Config) -> Path:
    """Get the video onto local disk. Local inputs are used in place, not copied."""
    path = Path(url_or_path).expanduser()
    if path.is_file():
        return path

    from yt_dlp import YoutubeDL

    outtmpl = str(workdir / "video.%(ext)s")

    def _download() -> None:
        with YoutubeDL(_ydl_opts(config, outtmpl)) as ydl:
            ydl.download([url_or_path])

    try:
        await asyncio.wait_for(asyncio.to_thread(_download), timeout=config.download_timeout)
    except asyncio.TimeoutError:
        raise AcquisitionError(
            f"download timed out after {config.download_timeout:.0f}s"
        ) from None
    except Exception as exc:
        raise AcquisitionError(_humanise(exc)) from exc

    candidates = sorted(workdir.glob("video.*"))
    if not candidates:
        raise AcquisitionError("yt-dlp reported success but produced no file")
    return candidates[0]


async def has_audio_stream(video: Path) -> bool:
    code, output = await _run(
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video),
        timeout=30,
    )
    return code == 0 and bool(output.strip())


async def extract_audio(video: Path, workdir: Path) -> Path | None:
    """Strip the audio track to mp3. Returns None when the clip is silent."""
    if not await has_audio_stream(video):
        return None

    audio = workdir / "audio.mp3"
    code, output = await _run(
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(video),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "128k",
        "-ac",
        "1",
        str(audio),
        timeout=300,
    )
    if code != 0 or not audio.is_file() or audio.stat().st_size == 0:
        raise AcquisitionError(f"audio extraction failed: {output.strip()[:200]}")
    return audio


async def _scene_timestamps(video: Path, config: Config) -> list[float]:
    """Timestamps of hard cuts, via ffmpeg's scene-score metadata."""
    code, output = await _run(
        "ffmpeg",
        "-v",
        "info",
        "-i",
        str(video),
        "-vf",
        f"select='gt(scene,{config.scene_threshold})',metadata=print:file=-",
        "-vsync",
        "vfr",
        "-f",
        "null",
        "-",
        timeout=300,
    )
    if code != 0:
        log.warning("scene detection failed; falling back to uniform sampling only")
        return []
    return [float(match) for match in _PTS_TIME.findall(output)]


def _merge_timestamps(
    scene: list[float], duration: float | None, config: Config
) -> tuple[list[float], bool]:
    """Combine scene cuts with a uniform floor, enforce a minimum gap, and cap.

    Returns (timestamps, was_capped). Scene cuts win when the cap forces a choice —
    they carry the most new information.
    """
    uniform: list[float] = []
    if duration and config.uniform_fps > 0:
        step = 1.0 / config.uniform_fps
        count = int(duration / step)
        uniform = [round(i * step, 3) for i in range(count + 1)]
    elif not scene:
        # No duration and no cuts detected — sample the opening as a last resort.
        uniform = [0.0, 1.0, 2.0]

    scene_set = {round(t, 3) for t in scene}
    merged = sorted(scene_set | set(uniform))

    # Minimum-gap dedup: a scene cut and a uniform tick landing together are the
    # same picture, so keep one. Prefers whichever comes first in time.
    spaced: list[float] = []
    for timestamp in merged:
        if not spaced or timestamp - spaced[-1] >= config.frame_min_gap:
            spaced.append(timestamp)
        elif timestamp in scene_set and spaced[-1] not in scene_set:
            spaced[-1] = timestamp  # upgrade a uniform tick to the real cut

    if len(spaced) <= config.max_frames:
        return spaced, False

    # Over the cap: keep every scene cut we can, then backfill uniformly.
    cuts = [t for t in spaced if t in scene_set][: config.max_frames]
    remaining = config.max_frames - len(cuts)
    if remaining > 0:
        others = [t for t in spaced if t not in scene_set]
        if others:
            stride = max(1, len(others) // remaining)
            cuts.extend(others[::stride][:remaining])
    return sorted(cuts), True


async def _grab_frame(video: Path, timestamp: float, target: Path, config: Config) -> Path | None:
    scale = f"scale='if(gt(iw,ih),{config.frame_long_edge},-2)':'if(gt(iw,ih),-2,{config.frame_long_edge})'"
    code, _ = await _run(
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{timestamp:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        scale,
        "-q:v",
        str(config.frame_quality),
        str(target),
        timeout=60,
    )
    if code != 0 or not target.is_file() or target.stat().st_size == 0:
        return None
    return target


async def extract_frames(
    video: Path, workdir: Path, config: Config, duration: float | None
) -> tuple[list[Frame], list[str]]:
    """Sample frames at scene cuts plus a uniform floor. Returns (frames, notes)."""
    notes: list[str] = []

    if duration is None:
        duration = await _probe_duration(video)

    scene = await _scene_timestamps(video, config)
    timestamps, capped = _merge_timestamps(scene, duration, config)
    if capped:
        notes.append(
            f"frame sampling hit the cap of {config.max_frames}; some frames were skipped "
            "(raise MAX_FRAMES for denser coverage)"
        )

    frames_dir = workdir / "frames"
    frames_dir.mkdir(exist_ok=True)

    semaphore = asyncio.Semaphore(6)

    async def grab(index: int, timestamp: float) -> Frame | None:
        async with semaphore:
            path = await _grab_frame(
                video, timestamp, frames_dir / f"frame-{index:04d}.jpg", config
            )
            return Frame(timestamp, path) if path is not None else None

    results = await asyncio.gather(
        *(grab(i, t) for i, t in enumerate(timestamps)), return_exceptions=True
    )
    frames = [r for r in results if isinstance(r, Frame)]

    if not frames:
        raise AcquisitionError("could not extract any frames from the video")

    effective_fps = len(frames) / duration if duration else 0.0
    log.info(
        "extracted %d frames (%d scene cuts) from %s — effective %.1f fps",
        len(frames),
        len(scene),
        video.name,
        effective_fps,
    )
    if duration and duration > 0 and effective_fps < 1.0:
        notes.append(
            f"frame density fell to {effective_fps:.1f} fps, at or below what a native-video "
            "model would sample — fast cuts may have been missed (raise MAX_FRAMES)"
        )
    return frames, notes
