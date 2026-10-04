"""ULID generation, written out rather than taken as a dependency.

WHY NOT A LIBRARY. The runtime dependency list is `jsonschema` and nothing else, and it
stays that way for a reason `verify` will need: an auditor in month fourteen installs
this on a machine that has never heard of it, and every transitive dependency is another
thing that must still resolve on that day. A ULID is forty lines. A supply chain is not.

WHY A ULID AT ALL, AND NOT A UUID. The bundle id is also the filename, so a plain
listing of `.witness/evidence/` is chronological without parsing anything - which is the
property an auditor uses when they have four hundred bundles and one question about
March. UUIDv4 gives a directory in random order.

The encoding is Crockford base32, which omits I, L, O and U so that a bundle id read
aloud from a printed workpaper cannot be transcribed wrong. `schemas/`'s pattern
`^[0-7][0-9A-HJKMNP-TV-Z]{25}$` is that alphabet; the leading `[0-7]` is not a separate
rule but a consequence - ten base32 characters carry fifty bits and the timestamp is
forty-eight, so the top two bits are always zero until the year 10889.
"""

from __future__ import annotations

import os
import time
from typing import Final

#: Crockford base32. I, L, O and U are absent by design - see the module docstring.
ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

TIMESTAMP_CHARS: Final = 10
RANDOM_CHARS: Final = 16
ULID_CHARS: Final = TIMESTAMP_CHARS + RANDOM_CHARS

_TIMESTAMP_BITS: Final = 48
_RANDOM_BITS: Final = 80


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        value, remainder = divmod(value, 32)
        out.append(ALPHABET[remainder])
    return "".join(reversed(out))


def new(now_ms: "int | None" = None, randomness: "int | None" = None) -> str:
    """A ULID string.

    `now_ms` and `randomness` exist so tests can pin the value. Nothing in the assembler
    passes them; a bundle id is never reproducible on purpose, because two assemblies of
    the same change are two distinct records of two distinct events.
    """
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    if not 0 <= ms < (1 << _TIMESTAMP_BITS):
        raise ValueError(f"timestamp out of ULID range: {ms}")
    rand = (
        int.from_bytes(os.urandom(10), "big") if randomness is None else randomness
    ) & ((1 << _RANDOM_BITS) - 1)
    return _encode(ms, TIMESTAMP_CHARS) + _encode(rand, RANDOM_CHARS)


def timestamp_ms(value: str) -> int:
    """Milliseconds since the epoch encoded in `value`.

    Only the sortability property is load-bearing, so this exists mainly to let tests
    assert that ordering by filename orders by creation time.
    """
    if len(value) != ULID_CHARS:
        raise ValueError(f"not a ULID: {value!r}")
    ms = 0
    for char in value[:TIMESTAMP_CHARS]:
        try:
            ms = ms * 32 + ALPHABET.index(char)
        except ValueError:
            raise ValueError(f"not a ULID: {value!r}") from None
    return ms
