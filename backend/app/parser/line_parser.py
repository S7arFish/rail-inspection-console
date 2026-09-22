"""Configurable, data-driven line parser for the inspection-car ASCII stream.

Everything the parser knows comes from ``config/parser.yaml``: field order,
field names, field types, the timestamp position + ``strptime`` format, the
end-of-batch token, the expected field count and the strict/non-strict mode.
No field semantics live in Python code.

Design rules that must not be broken:
* A physical line is *classified*, never silently discarded: the caller decides
  what to archive, and the caller always gets a :class:`ParsedLine` back.
* A bad timestamp must not drop a row (``ts`` becomes ``None``).
* ``strict: true`` adds an exception on top of the normal behaviour; it does not
  change what the non-strict path returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

logger = logging.getLogger(__name__)

# Valid per-field `type` values in parser.yaml. The frontend's declared vocabulary
# is int | float | string | timestamp, so the shipped config uses `float`;
# `number` is accepted as an alias that additionally normalises 1435.0 -> 1435.
FIELD_TYPES = ("string", "number", "int", "float", "timestamp")
KIND_DATA = "data"
KIND_CONTROL = "control"
KIND_INVALID = "invalid"
# The instrument's own column-name line (记录类型,测量方向,...). Protocol, like
# the terminator: it starts a batch and is never a measurement.
KIND_HEADER = "header"

_EOB_MATCH_MODES = ("contains", "exact")


class ParserConfigError(ValueError):
    """Raised when parser.yaml is structurally unusable."""


class LineSchemaError(ParserConfigError):
    """Raised in ``strict: true`` mode when a line does not match the schema."""


@dataclass(frozen=True)
class FieldSpec:
    index: int
    name: str
    type: str = "string"
    unit: str | None = None
    confirmed: bool = False
    note: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "type": self.type,
            "unit": self.unit,
            "confirmed": self.confirmed,
            "note": self.note,
        }

    def coerce(self, token: str) -> tuple[Any, str | None]:
        """Return ``(value, error_note)`` for one raw comma-separated token."""
        text = token.strip()
        if text == "":
            return None, None
        if self.type in ("number", "float"):
            try:
                value = float(text)
            except ValueError:
                return None, f"field {self.index} ({self.name}): {text!r} is not numeric"
            if self.type == "float":
                return value, None
            # `number`: keep integral values as ints so the JSON stays readable.
            return (int(value) if value.is_integer() else value), None
        if self.type == "int":
            try:
                return int(text, 10), None
            except ValueError:
                return None, f"field {self.index} ({self.name}): {text!r} is not an integer"
        # `string` and `timestamp` (handled elsewhere) keep the verbatim text.
        return text, None


@dataclass(frozen=True)
class EndOfBatchSpec:
    token: str = "OVER"
    match: str = "contains"

    def matches(self, line: str) -> bool:
        if self.match == "exact":
            return line.strip().upper() == self.token.strip().upper()
        return self.token.strip().upper() in line.upper()


@dataclass(frozen=True)
class HeaderSpec:
    """The DHJ-9 column-name line, when the export includes one.

    Matched as an exact ordered list of trimmed names, so a data row can never be
    mistaken for a header.
    """

    enabled: bool = True
    names: tuple[str, ...] = ()

    def matches(self, tokens: Sequence[str]) -> bool:
        if not self.enabled or not self.names:
            return False
        cleaned = tuple(token.strip() for token in tokens)
        return len(cleaned) == len(self.names) and cleaned == self.names


@dataclass(frozen=True)
class TimestampSpec:
    index: int = 7
    name: str = "timestamp"
    format: str = "%y%m%d-%H%M%S"
    include_in_fields: bool = False

    def parse(self, raw: str) -> tuple[str | None, str | None]:
        """Return ``(ts_raw, ts_iso_or_None)``; never raises, never drops."""
        text = raw.strip()
        if not text:
            return None, None
        try:
            parsed = datetime.strptime(text, self.format)
        except (ValueError, TypeError):
            return text, None
        if parsed.year < 1970:
            # `%y` has no century for 69-99; a 196x-199x reading of a live stream
            # is almost certainly a stale device clock, so we keep it naive but
            # still flag nothing. Data is never dropped.
            pass
        return text, parsed.isoformat(timespec="seconds")


@dataclass(frozen=True)
class ParserConfig:
    fields: tuple[FieldSpec, ...]
    timestamp: TimestampSpec = dc_field(default_factory=TimestampSpec)
    end_of_batch: EndOfBatchSpec = dc_field(default_factory=EndOfBatchSpec)
    header: HeaderSpec = dc_field(default_factory=HeaderSpec)
    delimiter: str = ","
    field_count: int = 12
    strict: bool = False
    encoding: str = "ascii"
    record_blank_lines: bool = True
    strip_chars: str = "\r\n\t "

    # ---------------------------------------------------------------- loading
    @classmethod
    def from_yaml(cls, path: str | Path) -> "ParserConfig":
        file_path = Path(path)
        if not file_path.is_file():
            raise ParserConfigError(f"parser config not found: {file_path}")
        try:
            data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:  # pragma: no cover - defensive
            raise ParserConfigError(f"cannot read parser config {file_path}: {exc}") from exc
        if not isinstance(data, Mapping):
            raise ParserConfigError(f"parser config {file_path} must be a mapping")
        return cls.from_mapping(data, source=str(file_path))

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], source: str = "<mapping>") -> "ParserConfig":
        raw_fields = data.get("fields")
        if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)) or not raw_fields:
            raise ParserConfigError(f"{source}: `fields` must be a non-empty list")

        specs: list[FieldSpec] = []
        seen_indexes: set[int] = set()
        seen_names: set[str] = set()
        for position, entry in enumerate(raw_fields):
            if not isinstance(entry, Mapping):
                raise ParserConfigError(f"{source}: fields[{position}] must be a mapping")
            try:
                index = int(entry["index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ParserConfigError(f"{source}: fields[{position}] needs an integer `index`") from exc
            if index in seen_indexes:
                raise ParserConfigError(f"{source}: duplicate field index {index}")
            name = str(entry.get("name") or f"raw_{index}").strip()
            if not name:
                raise ParserConfigError(f"{source}: fields[{position}] has an empty name")
            if name in seen_names:
                raise ParserConfigError(f"{source}: duplicate field name {name!r}")
            ftype = str(entry.get("type") or "string").strip().lower()
            if ftype not in FIELD_TYPES:
                raise ParserConfigError(f"{source}: field {name!r} has unknown type {ftype!r} (allowed: {FIELD_TYPES})")
            seen_indexes.add(index)
            seen_names.add(name)
            unit = entry.get("unit")
            specs.append(
                FieldSpec(
                    index=index,
                    name=name,
                    type=ftype,
                    unit=(str(unit) if unit not in (None, "", "null") else None),
                    confirmed=bool(entry.get("confirmed", False)),
                    note=(str(entry["note"]) if entry.get("note") is not None else None),
                )
            )
        specs.sort(key=lambda s: s.index)

        ts_raw = data.get("timestamp") or {}
        if not isinstance(ts_raw, Mapping):
            raise ParserConfigError(f"{source}: `timestamp` must be a mapping")
        ts_index = int(ts_raw.get("index", 7))
        ts_spec = TimestampSpec(
            index=ts_index,
            name=str(ts_raw.get("name") or "timestamp"),
            format=str(ts_raw.get("format") or "%y%m%d-%H%M%S"),
            include_in_fields=bool(ts_raw.get("include_in_fields", False)),
        )
        if ts_index not in seen_indexes:
            logger.warning(
                "parser config %s: timestamp index %s has no field definition, timestamp will still be read positionally",
                source, ts_index,
            )

        line_cfg = data.get("line") or {}
        if not isinstance(line_cfg, Mapping):
            raise ParserConfigError(f"{source}: `line` must be a mapping")
        eob_cfg = data.get("end_of_batch") or {}
        if not isinstance(eob_cfg, Mapping):
            raise ParserConfigError(f"{source}: `end_of_batch` must be a mapping")
        match_mode = str(eob_cfg.get("match") or "contains").strip().lower()
        if match_mode not in _EOB_MATCH_MODES:
            raise ParserConfigError(f"{source}: end_of_batch.match must be one of {_EOB_MATCH_MODES}")
        token = str(eob_cfg.get("token") or "OVER")

        header_cfg = data.get("header") or {}
        if not isinstance(header_cfg, Mapping):
            raise ParserConfigError(f"{source}: `header` must be a mapping")
        raw_names = header_cfg.get("names") or []
        if not isinstance(raw_names, Sequence) or isinstance(raw_names, (str, bytes)):
            raise ParserConfigError(f"{source}: header.names must be a list of strings")
        header = HeaderSpec(
            enabled=bool(header_cfg.get("enabled", True)),
            names=tuple(str(name).strip() for name in raw_names if str(name).strip()),
        )

        field_count = int(line_cfg.get("field_count", len(specs)))
        if field_count <= 0:
            raise ParserConfigError(f"{source}: line.field_count must be > 0")
        delimiter = str(line_cfg.get("delimiter") or ",")

        return cls(
            fields=tuple(specs),
            timestamp=ts_spec,
            end_of_batch=EndOfBatchSpec(token=token, match=match_mode),
            header=header,
            delimiter=delimiter,
            field_count=field_count,
            strict=bool(line_cfg.get("strict", False)),
            encoding=str(line_cfg.get("encoding") or "ascii"),
            record_blank_lines=bool(line_cfg.get("record_blank_lines", True)),
            strip_chars=str(line_cfg.get("strip_chars", "\r\n\t ")),
        )

    @classmethod
    def default(cls) -> "ParserConfig":
        """Last-resort in-memory config, equivalent to the shipped parser.yaml.

        Used only when parser.yaml is missing/broken (startup then keeps working
        instead of refusing to boot) and by tests. Keep in sync with
        config/parser.yaml — that file remains the single source of truth.
        """
        return cls.from_mapping(
            {
                "line": {"delimiter": ",", "field_count": 12, "strict": False},
                "timestamp": {"index": 7, "name": "timestamp", "format": "%y%m%d-%H%M%S"},
                "end_of_batch": {"token": "OVER", "match": "contains"},
                "header": {
                    "enabled": True,
                    "names": ["记录类型", "测量方向", "记录号", "线号", "工区", "杆号",
                              "测量位置", "时间", "高度", "拉出", "轨距"],
                },
                "fields": [
                    {"index": 0, "name": "record_type", "type": "int", "confirmed": True},
                    {"index": 1, "name": "measure_direction", "type": "int", "confirmed": True},
                    {"index": 2, "name": "record_no", "type": "int", "confirmed": True},
                    {"index": 3, "name": "line_no", "type": "int", "confirmed": True},
                    {"index": 4, "name": "work_area", "type": "int", "confirmed": True},
                    {"index": 5, "name": "pole_no", "type": "int", "confirmed": True},
                    {"index": 6, "name": "measure_position", "type": "int", "confirmed": True},
                    {"index": 7, "name": "timestamp", "type": "timestamp", "confirmed": True},
                    {"index": 8, "name": "height", "type": "float", "confirmed": True},
                    {"index": 9, "name": "pull_out", "type": "float", "confirmed": True},
                    {"index": 10, "name": "gauge", "type": "float", "confirmed": True},
                    # Position 11 has no counterpart in the 11-name instrument
                    # header: neutral name, unconfirmed, forever until documented.
                    {"index": 11, "name": "metric_extra_1", "type": "float", "confirmed": False},
                ],
            },
            source="ParserConfig.default()",
        )

    # ---------------------------------------------------------------- helpers
    def by_index(self) -> dict[int, FieldSpec]:
        return {spec.index: spec for spec in self.fields}

    @property
    def timestamp_field(self) -> FieldSpec | None:
        return self.by_index().get(self.timestamp.index)

    def public_field_list(self) -> list[dict[str, Any]]:
        """Rows for ``GET /api/parser/fields`` (timestamp included, flagged)."""
        return [spec.to_public_dict() for spec in self.fields]

    def legend_payload(self) -> dict[str, Any]:
        """The whole ``ParserFieldsResponse`` body - one source for HTTP + WS.

        `timestamp_field` is the column INDEX (that is what the frontend
        `types/domain.ts` declares), not its name.
        """
        return {
            "fields": self.public_field_list(),
            "timestamp_field": self.timestamp.index,
            "timestamp_name": self.timestamp.name,
            "timestamp_format": self.timestamp.format,
            "end_of_batch_token": self.end_of_batch.token,
            "expected_field_count": self.field_count,
            "delimiter": self.delimiter,
            "strict": self.strict,
        }



@dataclass
class ParsedLine:
    """Outcome of parsing one *physical* line (never ``None`` for a bad line)."""

    raw_line: str
    kind: str = KIND_INVALID
    fields: dict[str, Any] | None = None
    ts_raw: str | None = None
    ts: str | None = None
    parse_error: str | None = None
    # True when the timestamp could not be normalised (row is still valid data).
    timestamp_error: bool = False

    @property
    def is_data(self) -> bool:
        return self.kind == KIND_DATA

    @property
    def is_control(self) -> bool:
        return self.kind == KIND_CONTROL

    @property
    def is_header(self) -> bool:
        return self.kind == KIND_HEADER

    @property
    def starts_batch(self) -> bool:
        """Header or first data row — the two things that open a session."""
        return self.kind in (KIND_HEADER, KIND_DATA)

    def as_measurement_dict(self) -> dict[str, Any]:
        return {
            "fields": self.fields or {},
            "ts": self.ts,
            "ts_raw": self.ts_raw,
            "raw_line": self.raw_line,
        }


class LineParser:
    """Stateless parser: ``feed(line)`` -> :class:`ParsedLine`."""

    def __init__(self, config: ParserConfig) -> None:
        self.config = config
        self._specs = config.by_index()

    # ------------------------------------------------------------- line level
    def classify(self, line: str) -> str:
        text = self._strip(line)
        if text == "":
            return KIND_INVALID
        if self.config.end_of_batch.matches(text):
            return KIND_CONTROL
        if self._is_header(text):
            return KIND_HEADER
        return KIND_DATA  # candidate; parse() may still downgrade it to invalid

    def parse(self, line: str) -> ParsedLine:
        text = self._strip(line)
        cfg = self.config

        if text == "":
            # Nothing survived stripping. A pure CRLF carries no information and
            # is never archived; a whitespace-only line ("   ") is archived as
            # `invalid` while `record_blank_lines` is on, because it *is* a
            # physical line the car sent.
            softened = line.strip("\r\n")
            if cfg.record_blank_lines and softened != "":
                return ParsedLine(raw_line=softened, kind=KIND_INVALID, parse_error="blank line")
            return ParsedLine(raw_line="", kind=KIND_INVALID, parse_error="blank line")

        if cfg.end_of_batch.matches(text):
            return ParsedLine(raw_line=text, kind=KIND_CONTROL, parse_error=None)

        tokens = text.split(cfg.delimiter)

        if cfg.header.matches(tokens):
            # The instrument echoing its own column names: protocol, not data.
            return ParsedLine(raw_line=text, kind=KIND_HEADER, parse_error=None)

        if len(tokens) != cfg.field_count:
            message = f"expected {cfg.field_count} fields, got {len(tokens)}"
            if cfg.strict:
                raise LineSchemaError(f"{message} in line: {text!r}")
            return ParsedLine(raw_line=text, kind=KIND_INVALID, parse_error=message)

        values: dict[str, Any] = {}
        notes: list[str] = []
        ts_raw: str | None = None
        ts: str | None = None
        timestamp_error = False

        for index, token in enumerate(tokens):
            if index == cfg.timestamp.index:
                ts_raw, ts = cfg.timestamp.parse(token)
                timestamp_error = ts is None
                spec = self._specs.get(index)
                if cfg.timestamp.include_in_fields and spec is not None:
                    values[spec.name] = ts_raw
                continue
            spec = self._specs.get(index)
            if spec is None:
                # Position exists in the stream but has no configured name:
                # keep it under a generated placeholder key instead of losing it.
                placeholder = f"raw_{index}"
                cleaned = token.strip()
                existing = values.get(placeholder)
                if existing is None:
                    values[placeholder] = cleaned
                else:
                    values[f"raw_{index}_dup"] = cleaned
                continue
            value, error = spec.coerce(token)
            if error:
                notes.append(error)
            values[spec.name] = value

        if notes:
            # A per-field coercion problem does not invalidate the row: the raw
            # line is archived with the same note so nothing is unverifiable.
            return ParsedLine(
                raw_line=text,
                kind=KIND_INVALID,
                fields=values,
                ts_raw=ts_raw,
                ts=ts,
                parse_error="; ".join(notes),
                timestamp_error=timestamp_error,
            )

        return ParsedLine(
            raw_line=text,
            kind=KIND_DATA,
            fields=values,
            ts_raw=ts_raw,
            ts=ts,
            parse_error=("timestamp not parseable, kept as ts_raw" if timestamp_error else None),
            timestamp_error=timestamp_error,
        )

    def parse_many(self, lines: Iterable[str]) -> list[ParsedLine]:
        return [self.parse(line) for line in lines]

    def decode(self, data: bytes) -> str:
        """Decode wire bytes without ever raising on garbage."""
        try:
            return data.decode(self.config.encoding)
        except (LookupError, UnicodeDecodeError):
            return data.decode("ascii", errors="replace")

    # ----------------------------------------------------------------- private
    def _is_header(self, text: str) -> bool:
        cfg = self.config
        return bool(cfg.header.names) and cfg.header.matches(text.split(cfg.delimiter))

    def _strip(self, line: str) -> str:
        if not isinstance(line, str):
            raise TypeError(f"parser expects str, got {type(line).__name__}")
        return line.strip(self.config.strip_chars)


__all__ = [
    "FIELD_TYPES",
    "KIND_CONTROL",
    "KIND_DATA",
    "KIND_HEADER",
    "KIND_INVALID",
    "EndOfBatchSpec",
    "FieldSpec",
    "HeaderSpec",
    "LineParser",
    "LineSchemaError",
    "ParsedLine",
    "ParserConfig",
    "ParserConfigError",
    "TimestampSpec",
]
