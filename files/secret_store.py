"""Small secrets kept on disk, encrypted for the current Windows user.

On Windows the bytes go through DPAPI (CryptProtectData): only the same
Windows account on the same PC can read them back, so a copied data
folder, a backup or a shared screenshot of the file reveals nothing. A
file that can't be decrypted (another PC / account) reads as missing.
Elsewhere (macOS / Linux, untested) the text is stored as is, readable
only by the current user's file permissions.
"""

import ctypes
import os
import sys
from pathlib import Path

_PREFIX_DPAPI = b"DPAPI1:"
_PREFIX_PLAIN = b"PLAIN1:"
_ENTROPY = b"Upkeep secret store"  # ties the data to this app, on top of the user


if sys.platform == "win32":
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def _blob(data: bytes) -> _Blob:
        buffer = ctypes.create_string_buffer(data, len(data))
        return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))

    def _call(func, data: bytes) -> bytes:
        out = _Blob()
        entropy = _blob(_ENTROPY)
        if not func(ctypes.byref(_blob(data)), None, ctypes.byref(entropy), None, None,
                    _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out)):
            raise OSError(ctypes.get_last_error() or "DPAPI call failed")
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def _protect(data: bytes) -> bytes:
        return _PREFIX_DPAPI + _call(_crypt32.CryptProtectData, data)

    def _unprotect(data: bytes) -> bytes:
        return _call(_crypt32.CryptUnprotectData, data)
else:
    def _protect(data: bytes) -> bytes:
        return _PREFIX_PLAIN + data

    def _unprotect(data: bytes) -> bytes:  # pragma: no cover - only DPAPI data reaches here on Windows
        raise OSError("DPAPI data can't be read on this system")


def save(path: Path, text: str):
    """Writes `text` to `path`, encrypted for the current user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_protect(text.encode("utf-8")))
    if sys.platform != "win32":
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load(path: Path) -> str | None:
    """The text saved at `path`, or None if there's none or it can't be
    read here (another PC / Windows account, a damaged file)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        if raw.startswith(_PREFIX_DPAPI):
            return _unprotect(raw[len(_PREFIX_DPAPI):]).decode("utf-8")
        if raw.startswith(_PREFIX_PLAIN):
            return raw[len(_PREFIX_PLAIN):].decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return None


def delete(path: Path):
    path.unlink(missing_ok=True)
