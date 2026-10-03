"""Resolve bundled listing photos for the existing vision agent."""

import base64
from pathlib import Path


PHOTO_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "listing_photos"
PHOTO_PREFIX = "/listing-photos/"


def vision_image_url(url: str) -> str | None:
    if url.startswith(PHOTO_PREFIX):
        name = url.removeprefix(PHOTO_PREFIX)
        # Only plain JPEG filenames from the bundled directory may be read.
        if not name or Path(name).name != name or not name.endswith(".jpg"):
            return None
        path = PHOTO_DIRECTORY / name
        if not path.is_file() or path.is_symlink():
            return None
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    if url.startswith(("https://", "http://")) and "images.unsplash.com" not in url:
        return url
    return None
