"""Decimal-only helpers. Every financial value in this package is a ``decimal.Decimal``; JSON is parsed with
``parse_float=Decimal`` so a float never exists, and timestamps are integers (ns / ms)."""
from __future__ import annotations

import json
import time
from decimal import ROUND_DOWN, Decimal, InvalidOperation, getcontext
from typing import Any

getcontext().prec = 40

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)
BPS = Decimal(10_000)
HOURS_PER_YEAR = Decimal(24 * 365)


def loads(raw: str | bytes) -> Any:
    """JSON decode with Decimal for every non-integer number (never float)."""
    return json.loads(raw, parse_float=Decimal)


def dumps(obj: Any) -> str:
    """JSON encode; Decimals are written as strings (exact)."""
    return json.dumps(obj, default=_default, sort_keys=False, indent=2)


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return format(o, "f")
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def D(value: Any) -> Decimal:
    """Strict Decimal conversion from str / int / Decimal. Floats are refused."""
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            d = Decimal(value.strip())
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal string: {value!r}") from exc
        if not d.is_finite():
            raise ValueError(f"non-finite decimal: {value!r}")
        return d
    raise TypeError(f"refusing to convert {type(value).__name__} to Decimal (floats are forbidden)")


def D_opt(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return D(value)


def floor_to_step(qty: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def step_from_decimals(sz_decimals: int) -> Decimal:
    return Decimal(1).scaleb(-int(sz_decimals))


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def fmt(d: Decimal | None, places: int = 4) -> str:
    if d is None:
        return "n/a"
    return format(d.quantize(Decimal(1).scaleb(-places)), "f")
