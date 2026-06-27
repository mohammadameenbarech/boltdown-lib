"""
boltdown -- magnet link parsing utilities
"""

from __future__ import annotations

import base64
import re
from urllib.parse import unquote_plus

from .exceptions import InvalidMagnetError

# Matches standard hex (40 chars) and base32-encoded (32 chars) info hashes
_HEX_RE   = re.compile(r'^[0-9a-fA-F]{40}$')
_B32_RE   = re.compile(r'^[A-Z2-7]{32}$', re.IGNORECASE)


def validate(magnet: str) -> None:
    """
    Raise ``InvalidMagnetError`` if *magnet* is not a minimally valid magnet URI.

    Checks performed:
    - Starts with ``magnet:?``
    - Contains ``xt=urn:btih:`` field
    - The info-hash portion is a valid 40-char hex or 32-char base32 string
    """
    if not isinstance(magnet, str) or not magnet.strip().lower().startswith("magnet:?"):
        raise InvalidMagnetError("Magnet link must be a string starting with 'magnet:?'.")

    ih = extract_hash(magnet)
    if ih is None:
        raise InvalidMagnetError(
            "Magnet link is missing or has an invalid 'xt=urn:btih:' field. "
            f"Got: {magnet[:80]!r}"
        )


def extract_hash(magnet: str) -> str | None:
    """
    Extract and normalise the info-hash from a magnet link.

    Returns a lowercase 40-char hex string, or ``None`` if not found / invalid.
    Base32-encoded hashes are decoded automatically.
    """
    try:
        for part in magnet.split("&"):
            key, _, value = part.partition("=")
            if key.lower() in ("xt", "magnet:?xt"):
                # value looks like: urn:btih:<hash>
                ih = value.split(":")[-1].split("&")[0].strip()
                if _HEX_RE.match(ih):
                    return ih.lower()
                if _B32_RE.match(ih):
                    return _b32_to_hex(ih)
    except Exception:
        pass
    return None


def extract_name(magnet: str) -> str | None:
    """Return the display name (dn) from a magnet link, or ``None``."""
    try:
        for part in magnet.split("&"):
            key, _, value = part.partition("=")
            if key.lower() == "dn":
                return unquote_plus(value)
    except Exception:
        pass
    return None


def extract_trackers(magnet: str) -> list[str]:
    """Return all tracker URLs (tr) from a magnet link."""
    trackers: list[str] = []
    try:
        for part in magnet.split("&"):
            key, _, value = part.partition("=")
            if key.lower() == "tr":
                trackers.append(unquote_plus(value))
    except Exception:
        pass
    return trackers


# -- Internals ------------------------------------------------------------------

def _b32_to_hex(b32: str) -> str:
    """Convert a base32-encoded info hash to a lowercase hex string."""
    raw = base64.b32decode(b32.upper())
    return raw.hex()
