"""Assembly of the two-section plain-text block the calling model receives."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaInfo:
    title: str | None = None
    platform: str | None = None
    duration: float | None = None


def format_duration(seconds: float | None) -> str | None:
    if seconds is None or seconds <= 0:
        return None
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def render(info: MediaInfo, transcript: str, visual: str, notes: list[str] | None = None) -> str:
    """Build the final tool output. Header lines are omitted when unknown."""
    lines: list[str] = []

    if info.title:
        lines.append(f"TITLE: {info.title}")
    if info.platform:
        lines.append(f"PLATFORM: {info.platform}")
    pretty_duration = format_duration(info.duration)
    if pretty_duration:
        lines.append(f"DURATION: {pretty_duration}")

    if lines:
        lines.append("")

    lines.append("=== TRANSCRIPT ===")
    lines.append(transcript.strip() or "(empty)")
    lines.append("")
    lines.append("=== VISUAL DESCRIPTION ===")
    lines.append(visual.strip() or "(empty)")

    if notes:
        lines.append("")
        lines.append("=== NOTES ===")
        lines.extend(f"- {note}" for note in notes)

    return "\n".join(lines)
