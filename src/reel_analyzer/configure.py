"""Save settings once, so no host config has to carry the API key.

    reel-analyzer-configure                 # prompt for the key
    reel-analyzer-configure --show          # show current settings, key masked
    reel-analyzer-configure --set VISION_MODEL=google/gemma-4-31b-it

Writes ~/.config/reel-analyzer/config.json with 0600 permissions. Environment
variables still win over the file, so a host can override per-server.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from .config import ConfigError, load_config, read_settings_file, settings_path, write_settings_file

SECRET_KEYS = {"OPENROUTER_API_KEY"}


def _mask(name: str, value: object) -> str:
    text = str(value)
    if name in SECRET_KEYS and len(text) > 8:
        return f"{text[:6]}…{text[-4:]} ({len(text)} chars)"
    return text


def _show() -> int:
    path = settings_path()
    stored = read_settings_file()
    if not stored:
        print(f"No settings file yet at {path}")
    else:
        print(f"{path}\n")
        for name, value in sorted(stored.items()):
            print(f"  {name} = {_mask(name, value)}")

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"\nNot ready: {exc}")
        return 1

    print("\nEffective (environment overrides the file):")
    print(f"  vision model        {config.vision_model}")
    print(f"  transcription model {config.transcription_model}")
    print(f"  feed mode           {config.feed_mode}")
    print(f"  frame cap           {config.max_frames}")
    print("\nReady.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="reel-analyzer-configure", description=__doc__)
    parser.add_argument("--show", action="store_true", help="print current settings and exit")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="set any setting, repeatable (e.g. --set MAX_FRAMES=60)",
    )
    args = parser.parse_args()

    if args.show:
        sys.exit(_show())

    values: dict[str, object] = {}
    for pair in args.set:
        if "=" not in pair:
            parser.error(f"--set expects NAME=VALUE, got {pair!r}")
        name, value = pair.split("=", 1)
        values[name.strip().upper()] = value.strip()

    if not values:
        existing = read_settings_file().get("OPENROUTER_API_KEY")
        if existing:
            print(f"An API key is already saved ({_mask('OPENROUTER_API_KEY', existing)}).")
            print("Press Enter to keep it, or paste a new one.")
        key = getpass.getpass("OpenRouter API key (input hidden): ").strip()
        if key:
            values["OPENROUTER_API_KEY"] = key
        elif not existing:
            print("No key entered; nothing saved.", file=sys.stderr)
            sys.exit(1)

    try:
        path = write_settings_file(values)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Saved to {path} (permissions 0600).")
    for name in values:
        print(f"  {name} = {_mask(name, values[name])}")
    sys.exit(_show())


if __name__ == "__main__":
    main()
