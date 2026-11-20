"""Custom card images ("Edit card" in Settings — artist proofs, signed or
altered cards): the user's own images for a specific printing (set +
collector number) — a front and / or a back. The front replaces that
printing's normal image everywhere in the app; the back is shown when a
showcase is flipped.

Images are copied into paths.ARTIST_PROOFS_DIR (user data, not cache);
the index paths.ARTIST_PROOFS_PATH maps "set|cn" -> {"name", "set", "cn",
"front": filename, "back": filename or None}.

Every card image in the app is fetched through image_cache.get_image_path
with a cache name — "card_<set>_<cn>" for fronts, "back_<set>_<cn>" for
backs (see scryfall.card_image_cache_name / back_cache_name) — and it asks
proof_path_for_cache_name() first, so proofs show everywhere without any
screen knowing about them.
"""

import shutil
import threading
from pathlib import Path

import cache_io
import paths
import scryfall

_lock = threading.Lock()  # image loads run on worker threads
_by_cache_name = None  # cache name -> Path, built lazily from the index


def load() -> dict:
    return cache_io.read_json(paths.ARTIST_PROOFS_PATH) or {}


def key(set_code: str, cn: str) -> str:
    return f"{str(set_code).lower()}|{cn}"


def proof_for(set_code: str, cn: str) -> dict | None:
    """The index entry for a printing, or None."""
    return load().get(key(set_code, cn))


KEEP = None  # update(): leave that side as it is
CLEAR = False  # update(): back to the normal image

# What kind of special copy a printing is — ticked in the Edit card window,
# searchable as is:proof / is:altered / is:signed (card_search).
FLAGS = {"proof": "Artist proof", "altered": "Altered", "signed": "Signed"}


def update(name: str, set_code: str, cn: str, front=KEEP, back=KEEP, flags: dict | None = None):
    """Changes a printing's custom images and flags. front / back: an
    image file to copy in, CLEAR to go back to the normal image, or KEEP.
    flags: {flag: bool} for FLAGS (None keeps them). A printing left with
    no custom image and no flag is removed from the index."""
    index = load()
    k = key(set_code, cn)
    entry = index.get(k) or {"name": name, "set": str(set_code).lower(), "cn": str(cn), "front": None, "back": None}
    paths.ARTIST_PROOFS_DIR.mkdir(parents=True, exist_ok=True)
    for side, action in (("front", front), ("back", back)):
        if action is KEEP:
            continue
        if entry[side]:  # replaced or cleared: drop the old copy
            (paths.ARTIST_PROOFS_DIR / entry[side]).unlink(missing_ok=True)
            entry[side] = None
        if action is not CLEAR:
            filename = f"{_safe(set_code)}_{_safe(cn)}_{side}{Path(action).suffix.lower() or '.png'}"
            shutil.copyfile(action, paths.ARTIST_PROOFS_DIR / filename)
            entry[side] = filename
    for flag, value in (flags or {}).items():
        entry[flag] = bool(value)
    if entry["front"] or entry["back"] or any(entry.get(flag) for flag in FLAGS):
        index[k] = entry
    else:
        index.pop(k, None)
    _save(index)


def set_proof(name: str, set_code: str, cn: str, front: str | None = None, back: str | None = None):
    """update() with files only (None keeps that side)."""
    update(name, set_code, cn, front=front, back=back)


def remove_back(set_code: str, cn: str):
    index = load()
    entry = index.get(key(set_code, cn))
    if entry and entry["back"]:
        (paths.ARTIST_PROOFS_DIR / entry["back"]).unlink(missing_ok=True)
        entry["back"] = None
        _save(index)


def remove_proof(set_code: str, cn: str):
    index = load()
    entry = index.pop(key(set_code, cn), None)
    if entry:
        for side in ("front", "back"):
            if entry[side]:
                (paths.ARTIST_PROOFS_DIR / entry[side]).unlink(missing_ok=True)
        _save(index)


def image_path(entry: dict, side: str) -> Path | None:
    return paths.ARTIST_PROOFS_DIR / entry[side] if entry.get(side) else None


def proof_path_for_cache_name(cache_name: str) -> Path | None:
    """The proof image to use instead of a card image cache name, if any
    ("card_<set>_<cn>" -> front, "back_<set>_<cn>" -> back)."""
    global _by_cache_name
    with _lock:
        if _by_cache_name is None:
            _by_cache_name = {}
            for entry in load().values():
                printing = {"set": entry["set"], "cn": entry["cn"]}
                if entry.get("front"):
                    _by_cache_name[scryfall.card_image_cache_name(printing)] = paths.ARTIST_PROOFS_DIR / entry["front"]
                if entry.get("back"):
                    _by_cache_name[scryfall.back_cache_name(printing)] = paths.ARTIST_PROOFS_DIR / entry["back"]
        path = _by_cache_name.get(cache_name)
    return path if path is not None and path.exists() else None


_flags_by_key = None  # "set|cn" -> set of flags, built lazily (searches call this a lot)


def flags_for(set_code: str, cn: str) -> set:
    """The FLAGS ticked for a printing (empty set if none)."""
    global _flags_by_key
    with _lock:
        if _flags_by_key is None:
            _flags_by_key = {
                k: {flag for flag in FLAGS if entry.get(flag)} for k, entry in load().items()
            }
        return _flags_by_key.get(key(set_code, cn), set())


def _save(index: dict):
    global _by_cache_name, _flags_by_key
    cache_io.write_json(paths.ARTIST_PROOFS_PATH, index, indent=2)
    with _lock:
        _by_cache_name = None  # rebuilt on next lookup
        _flags_by_key = None


def _safe(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-" else "_" for ch in str(text))
