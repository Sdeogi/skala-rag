"""Korean particle (조사) helper for generated sentences."""

from __future__ import annotations

_LATIN_WITH_BATCHIM = set("bcdgklmnpt")
_DIGITS_WITH_BATCHIM = set("013678")


def has_batchim(word: str) -> bool:
    text = str(word or "").rstrip(")]}\"' ")
    if not text:
        return False
    last = text[-1]
    if "가" <= last <= "힣":
        return (ord(last) - 0xAC00) % 28 != 0
    if last.isdigit():
        return last in _DIGITS_WITH_BATCHIM
    if last.isascii() and last.isalpha():
        return last.lower() in _LATIN_WITH_BATCHIM
    return False


def josa(word: str, with_batchim: str, without_batchim: str) -> str:
    """Attach the right particle: josa("KIVI", "을", "를") -> "KIVI를"."""
    return f"{word}{with_batchim if has_batchim(word) else without_batchim}"
