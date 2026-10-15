"""Sensitive information detection and masking (mainland China formats + e-mail).

Applied at ingest (chunk text before it is stored and indexed) and/or at output (answers,
citation quotes, search snippets), see settings.pii_mask_on_ingest / pii_mask_on_output.

Types: phone (mobile numbers), id_card (18-digit resident ID, checksum-verified), bank_card
(13-19 digits, Luhn-verified), email. Matches never overlap; ID cards win over bank cards.
"""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

PII_TYPES = ("id_card", "bank_card", "phone", "email")

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "id_card": re.compile(
        r"(?<![0-9A-Za-z])[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])\d{2}\d{3}[\dXx](?![0-9A-Za-z])"
    ),
    "bank_card": re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)"),
    "phone": re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?!\d)"),
    "email": re.compile(
        r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
    ),
}


def _valid_id_card(value: str) -> bool:
    body, check = value[:17], value[17].upper()
    total = sum(int(d) * w for d, w in zip(body, _ID_WEIGHTS, strict=True))
    return _ID_CHECK[total % 11] == check


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


_VALIDATORS: dict[str, Callable[[str], bool]] = {
    "id_card": _valid_id_card,
    "bank_card": lambda v: 13 <= len(_digits(v)) <= 19 and _luhn(_digits(v)),
    "phone": lambda v: True,
    "email": lambda v: True,
}


def _keep_ends(value: str, head: int, tail: int) -> str:
    chars = list(value)
    positions = [i for i, c in enumerate(chars) if c.isalnum()]
    for i in positions[head : len(positions) - tail]:
        chars[i] = "*"
    return "".join(chars)


def _mask_email(value: str) -> str:
    local, _, domain = value.partition("@")
    return f"{local[:1]}***@{domain}"


_MASKERS: dict[str, Callable[[str], str]] = {
    "id_card": lambda v: _keep_ends(v, 3, 4),
    "bank_card": lambda v: _keep_ends(v, 4, 4),
    "phone": lambda v: _keep_ends(v, len(_digits(v)) - 8, 4),
    "email": _mask_email,
}


@dataclass(frozen=True)
class PiiMatch:
    type: str
    start: int
    end: int
    value: str


class PiiMasker:
    def __init__(self, types: Iterable[str]) -> None:
        wanted = set(types)
        unknown = wanted - set(PII_TYPES)
        if unknown:
            raise ValueError(f"Unknown PII types: {sorted(unknown)}")
        self.types = [t for t in PII_TYPES if t in wanted]

    def __bool__(self) -> bool:
        return bool(self.types)

    def find(self, text: str) -> list[PiiMatch]:
        taken: list[tuple[int, int]] = []
        found: list[PiiMatch] = []
        for kind in self.types:
            for m in _PATTERNS[kind].finditer(text):
                start, end = m.span()
                if any(start < e and s < end for s, e in taken):
                    continue
                if not _VALIDATORS[kind](m.group()):
                    continue
                taken.append((start, end))
                found.append(PiiMatch(kind, start, end, m.group()))
        return sorted(found, key=lambda x: x.start)

    def mask(self, text: str) -> str:
        if not self.types or not text:
            return text
        out: list[str] = []
        pos = 0
        for m in self.find(text):
            out.append(text[pos : m.start])
            out.append(_MASKERS[m.type](m.value))
            pos = m.end
        out.append(text[pos:])
        return "".join(out)


class StreamMasker:
    """Masks a token stream. The trailing `hold` characters are buffered because a number can
    be split across tokens; a pending match is only released once it cannot grow anymore."""

    def __init__(self, masker: PiiMasker, hold: int = 32) -> None:
        self.masker = masker
        self.hold = hold
        self._buffer = ""

    def feed(self, token: str) -> str:
        self._buffer += token
        if len(self._buffer) <= self.hold:
            return ""
        cut = len(self._buffer) - self.hold
        # Never cut inside a (possible) match: move the cut before it.
        for m in self.masker.find(self._buffer):
            if m.start < cut < m.end:
                cut = m.start
                break
        ready, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return self.masker.mask(ready)

    def flush(self) -> str:
        rest, self._buffer = self._buffer, ""
        return self.masker.mask(rest)
