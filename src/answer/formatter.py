"""Deterministic formatting for DataMate submission answers."""

import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Literal


AnswerType = Literal[
    "number", "percent", "string", "date", "boolean", "list", "table",
    "unanswerable", "abstain",
]
NumberKind = Literal["money", "count", "decimal"]


def _number(value: Any, kind: NumberKind) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("numeric answers must be numbers, not strings or booleans")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("numeric answers must be finite")
    decimal_value = Decimal(str(value))
    if kind in ("money", "count"):
        if kind == "count" and decimal_value != decimal_value.to_integral_value():
            raise ValueError("counts must be whole numbers")
        return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return float(decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _json_value(value: Any) -> Any:
    """Validate cells without changing names, order, or numeric meaning."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("table/list numbers must be finite")
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("table/list numbers must be finite")
        return value
    if isinstance(value, (date, datetime)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    raise ValueError(f"unsupported table/list cell: {type(value).__name__}")


def format_answer(
    question_id: str,
    answer_type: AnswerType,
    value: Any = None,
    *,
    number_kind: NumberKind | None = None,
    date_granularity: Literal["day", "month"] = "day",
    reason: str | None = None,
) -> dict[str, Any]:
    """Build one submission record from a computed value.

    ``number_kind`` is required for ``number`` because money, counts, and
    other numeric measures have different rounding rules in the rulebook.
    Percent values must already be on the 0–100 scale.
    """
    if not isinstance(question_id, str) or not question_id:
        raise ValueError("question_id must be a non-empty string")
    record: dict[str, Any] = {"id": question_id, "type": answer_type}

    if answer_type in ("unanswerable", "abstain"):
        if value is not None:
            raise ValueError(f"{answer_type} must not have an answer value")
        if answer_type == "unanswerable" and reason is not None:
            if not isinstance(reason, str):
                raise ValueError("reason must be a string")
            record["reason"] = reason
        return record

    if value is None:
        raise ValueError(f"{answer_type} requires an answer value")
    if answer_type == "number":
        if number_kind not in ("money", "count", "decimal"):
            raise ValueError("number_kind must be money, count, or decimal")
        record["answer"] = _number(value, number_kind)
    elif answer_type == "percent":
        record["answer"] = _number(value, "decimal")
    elif answer_type == "string":
        if not isinstance(value, str):
            raise ValueError("string answers must be strings")
        record["answer"] = value
    elif answer_type == "date":
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            value = value.strftime("%Y-%m") if date_granularity == "month" else value.isoformat()
        pattern = r"\d{4}-\d{2}" if date_granularity == "month" else r"\d{4}-\d{2}-\d{2}"
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError(f"date answer must be YYYY-MM{'' if date_granularity == 'month' else '-DD'}")
        try:
            date.fromisoformat(value + "-01" if date_granularity == "month" else value)
        except ValueError as exc:
            raise ValueError("date answer must be a real calendar date") from exc
        record["answer"] = value
    elif answer_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("boolean answers must be true or false")
        record["answer"] = value
    elif answer_type == "list":
        if not isinstance(value, (list, tuple)):
            raise ValueError("list answers must be arrays")
        record["answer"] = [_json_value(item) for item in value]
    elif answer_type == "table":
        if not isinstance(value, dict) or set(value) != {"columns", "rows"}:
            raise ValueError("table answers need columns and rows")
        columns, rows = value["columns"], value["rows"]
        if not isinstance(columns, list) or not columns or not all(isinstance(c, str) for c in columns):
            raise ValueError("table columns must be a non-empty string list")
        if not isinstance(rows, list) or not all(isinstance(row, (list, tuple)) and len(row) == len(columns) for row in rows):
            raise ValueError("every table row must match the columns")
        record["answer"] = {"columns": columns, "rows": [[_json_value(cell) for cell in row] for row in rows]}
    else:
        raise ValueError(f"unknown answer type: {answer_type}")
    return record


def to_json_line(record: dict[str, Any]) -> str:
    """Serialize one record for submission.jsonl."""
    return json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
