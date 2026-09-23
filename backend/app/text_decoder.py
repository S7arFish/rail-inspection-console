"""Serial wire bytes -> text, with one explicit decoding strategy.

The DHJ-9's data lines are pure ASCII, but its header line is Chinese and the
device encodes it as GBK/GB18030. A UTF-8 terminal therefore shows mojibake, and
a naive ``decode("utf-8", errors="replace")`` would turn the header into
replacement characters that the parser can no longer recognise.

So decoding happens here, once, in a fixed order, and nothing else in the
service layer guesses about encodings:

1. pure ASCII  -> ascii (the common case: every measurement row and ``OVER``)
2. preferred codec from the parser config, when it is neither of the below
3. UTF-8 strict
4. GB18030 strict (a superset of GBK, so it also covers GBK-only devices)
5. GB18030 with ``errors="replace"`` and ``had_decode_error=True``

Step 5 must never raise: one corrupt line can't be allowed to kill the reader
thread. No third-party detection library is used.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tried after the ASCII fast path, in order.
FALLBACK_ENCODINGS: tuple[str, ...] = ("utf-8", "gb18030")

# Last resort. GB18030 keeps Chinese text readable far better than UTF-8 when
# the device is a Chinese instrument, so it wins the replacement pass.
REPLACEMENT_ENCODING = "gb18030"


@dataclass(frozen=True)
class DecodedSerialLine:
    """What one physical wire line turned into.

    `encoding` is the codec that actually worked; ``*(replace)`` is appended when
    the value came from the lossy last resort.
    """

    text: str
    encoding: str
    had_decode_error: bool = False

    @property
    def is_ascii(self) -> bool:
        return self.encoding == "ascii"


def _candidate_chain(preferred: str | None) -> list[str]:
    chain: list[str] = []
    if preferred:
        normalised = preferred.strip().lower()
        if normalised and normalised not in ("ascii", *FALLBACK_ENCODINGS):
            chain.append(normalised)
    chain.extend(FALLBACK_ENCODINGS)
    return chain


def decode_serial_line(raw: bytes | bytearray | memoryview, *, preferred: str | None = None) -> DecodedSerialLine:
    """Decode one physical line without ever raising.

    Line terminators are deliberately left in place: ``LineParser`` owns
    stripping, so the decoder stays a pure bytes -> text step.
    """
    data = raw if isinstance(raw, bytes) else bytes(raw)

    if not data:
        return DecodedSerialLine(text="", encoding="ascii", had_decode_error=False)

    if data.isascii():
        return DecodedSerialLine(text=data.decode("ascii"), encoding="ascii", had_decode_error=False)

    for encoding in _candidate_chain(preferred):
        try:
            return DecodedSerialLine(text=data.decode(encoding), encoding=encoding, had_decode_error=False)
        except LookupError:
            continue  # unknown codec in config: skip it, never crash
        except UnicodeDecodeError:
            continue

    return DecodedSerialLine(
        text=data.decode(REPLACEMENT_ENCODING, errors="replace"),
        encoding=f"{REPLACEMENT_ENCODING}(replace)",
        had_decode_error=True,
    )


__all__ = [
    "FALLBACK_ENCODINGS",
    "REPLACEMENT_ENCODING",
    "DecodedSerialLine",
    "decode_serial_line",
]
