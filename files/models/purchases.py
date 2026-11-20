"""Imported purchases (Cardmarket orders — see cardmarket.py), one JSON
file each under data/purchases/. User data, not cache: clearCache never
touches it.

A purchase is a dict: "id", "name", "seller", "date", "total", ... plus
"entries" — card entries in the same shape as Moxfield collection
entries, so the Collection screen can show a purchase as-is.
"""

import cache_io
import paths


def list_all() -> list:
    """Every saved purchase, newest first (by order date, then import time)."""
    purchases = []
    if paths.PURCHASES_DIR.exists():
        for path in paths.PURCHASES_DIR.glob("*.json"):
            data = cache_io.read_json(path)
            if data:
                purchases.append(data)
    purchases.sort(key=lambda p: (p.get("date") or "", p.get("imported_at") or ""), reverse=True)
    return purchases


def exists(purchase_id: str) -> bool:
    return paths.purchase_path(purchase_id).exists()


def save(purchase: dict):
    """Writes (or overwrites) a purchase under its "id"."""
    cache_io.write_json(paths.purchase_path(purchase["id"]), purchase, indent=1)


def delete(purchase_id: str):
    path = paths.purchase_path(purchase_id)
    if path.exists():
        path.unlink()


def load(purchase_id: str):
    """One purchase, or None if it doesn't exist."""
    return cache_io.read_json(paths.purchase_path(purchase_id))


def received_entries(purchase: dict) -> list:
    """The purchase's entries minus cards removed as not received (an
    entry's "removed": copies taken off — see PurchasesScreen). Entries
    with nothing left are dropped; the rest are copies with the reduced
    quantity, so the stored entries keep their original count."""
    received = []
    for e in purchase["entries"]:
        left = e["quantity"] - e.get("removed", 0)
        if left > 0:
            received.append(e if left == e["quantity"] else {**e, "quantity": left})
    return received
