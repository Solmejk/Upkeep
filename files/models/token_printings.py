"""Default printings for tokens: which printing (art) to show for a token
wherever a deck makes it, chosen in the token's popup (Set default
printing...). Saved in data/token_printings.json (user data — clearCache
never touches it), keyed by Moxfield's id for the token itself
("uid" on a deck token — the same for every printing of it):
    {uid: {"scryfall_id", "set", "cn", "set_name"}}
"""

import cache_io
import paths
import scryfall


def _load() -> dict:
    return cache_io.read_json(paths.TOKEN_PRINTINGS_PATH) or {}


def set_default(uid: str, printing: dict | None):
    """Saves a Scryfall card object as the token's default printing, or
    removes the default (back to each deck's own printing) with None."""
    data = _load()
    if printing is None:
        data.pop(uid, None)
    else:
        data[uid] = {
            "scryfall_id": printing["id"],
            "set": printing["set"],
            "cn": printing["collector_number"],
            "set_name": printing.get("set_name", ""),
        }
    cache_io.write_json(paths.TOKEN_PRINTINGS_PATH, data, indent=1)


def deck_printing(token: dict) -> dict:
    """The token as the deck lists it (undoes apply())."""
    return token.get("_deck_token", token)


def apply(token: dict) -> dict:
    """The token with its default printing, if one is set: a copy with
    set / cn / scryfall_id / image_url replaced (the deck's version kept
    under "_deck_token"), else the token unchanged."""
    token = deck_printing(token)
    chosen = _load().get(token.get("uid"))
    if not chosen:
        return token
    return {
        **token,
        "set": chosen["set"],
        "cn": chosen["cn"],
        "scryfall_id": chosen["scryfall_id"],
        "image_url": scryfall.image_url(chosen["scryfall_id"]),
        "_deck_token": token,
    }
