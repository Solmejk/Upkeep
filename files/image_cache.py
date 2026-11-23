"""Generic on-disk image cache, keyed by an arbitrary caller-supplied
name (card printings, deck commander art, user profile pictures — see
scryfall.card_image_cache_name for the card-specific naming scheme).
"""

import os
import threading
import time
from pathlib import Path
import requests

from models import artist_proofs
import scryfall
from paths import IMAGES_DIR as CACHE_DIR
from scryfall import HEADERS  # also used for non-Scryfall images (e.g. Moxfield profile pics) — Scryfall's User-Agent requirement is the strictest, so it works everywhere


def get_image_path(url: str, name: str) -> Path | None:
    """
    Return a local path to the image, downloading if not cached.
    `name` is used as the filename (e.g. username for profile pics).
    Returns None if there's no URL or the fetch fails. The user's custom
    image for that printing (models.artist_proofs) replaces it, if any.
    """
    custom = artist_proofs.proof_path_for_cache_name(name)
    if custom is not None:
        return custom
    return get_original_image_path(url, name)


def get_original_image_path(url: str, name: str, timeout: int = 10, retries: int = 0) -> Path | None:
    """get_image_path without the custom-image override — the real
    Scryfall image (the card image editor's "original"). timeout /
    retries: for big images (the Token Printer's ~1.8 MB print PNGs,
    whose first request can be slow), wait longer and try again."""
    if not url:
        return None

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use the URL's extension if present, otherwise default to png
    ext = Path(url).suffix or ".png"
    path = CACHE_DIR / f"{name}{ext}"
    
    if path.exists():
        return path
    
    for attempt in range(retries + 1):
        try:
            if url.startswith(scryfall.API_ROOT):
                # an image by name through Scryfall's API (not its image
                # servers): paced and backed off like every API request
                response = scryfall.api_get(url, timeout=timeout)
            else:
                response = requests.get(url, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == retries:
                return None
            time.sleep(2 * (attempt + 1))

    # Write to a unique temp file and rename into place, so a reader (or a
    # second download of the same image — the background prefetcher and an
    # on-screen load can overlap) never sees a half-written file.
    tmp = CACHE_DIR / f"{name}.{threading.get_ident()}.part"
    try:
        tmp.write_bytes(response.content)
        os.replace(tmp, path)
    except OSError:
        # Windows refuses the rename if the other copy just landed and is
        # open for reading — that copy is just as good.
        tmp.unlink(missing_ok=True)
        if not path.exists():
            return None
    return path