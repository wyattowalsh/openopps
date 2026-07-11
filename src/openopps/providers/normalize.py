from __future__ import annotations

from typing import Sequence

from openopps.models import JsonDict

__all__ = [
    "format_salary",
    "number",
    "salary_components",
    "salary_display",
    "string",
]


def string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def format_salary(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _compensation_bound(compensation: JsonDict, keys: Sequence[str]) -> float | None:
    raw = None
    for key in keys:
        candidate = compensation.get(key)
        if candidate:
            raw = candidate
            break
    return number(raw)


def salary_components(
    compensation: JsonDict | None,
    *,
    min_keys: Sequence[str] = ("minValue", "min", "minimum"),
    max_keys: Sequence[str] = ("maxValue", "max", "maximum"),
) -> tuple[float | None, float | None, str | None]:
    if not compensation:
        return None, None, None
    salary_min = _compensation_bound(compensation, min_keys)
    salary_max = _compensation_bound(compensation, max_keys)
    currency = compensation.get("currency") or compensation.get("currencyCode")
    return salary_min, salary_max, str(currency) if currency else None


def salary_display(
    salary_min: float | None, salary_max: float | None, currency: str | None
) -> str | None:
    values = [value for value in (salary_min, salary_max) if value is not None]
    if not values:
        return None
    prefix = f"{currency} " if currency else ""
    if salary_min is not None and salary_max is not None:
        return f"{prefix}{format_salary(salary_min)} - {format_salary(salary_max)}"
    return f"{prefix}{format_salary(values[0])}"