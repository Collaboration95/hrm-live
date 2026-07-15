#!/usr/bin/env python3
"""Build the macOS ICNS asset from the project-owned 1024px PNG source."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "assets/HRMLive.iconset/icon_512x512@2x.png"
DESTINATION = PROJECT_ROOT / "assets/HRMLive.icns"
ICON_SIZES = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]


def main() -> None:
    """Create a valid ICNS file without relying on macOS ``iconutil``."""

    with Image.open(SOURCE) as source:
        if source.width < 1024 or source.height < 1024:
            raise ValueError(f"{SOURCE} must be at least 1024×1024 pixels")
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        source.convert("RGBA").save(DESTINATION, format="ICNS", sizes=ICON_SIZES)


if __name__ == "__main__":
    main()
