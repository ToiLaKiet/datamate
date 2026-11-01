"""Small output contracts for the two LLM planning calls."""

ANSWER_TYPES = ["number", "percent", "string", "date", "boolean", "list", "table"]

PLAN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_type": {"enum": ANSWER_TYPES + [None]},
        "number_kind": {"enum": ["money", "count", "decimal", None]},
        "date_granularity": {"enum": ["day", "month", None]},
        "metric": {"type": ["string", "null"]},
        "definitions": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "array", "items": {"type": "string"}},
        "time_window": {
            "type": ["object", "null"],
            "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
            "required": ["start", "end"],
            "additionalProperties": False,
        },
        "comparison_windows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "start": {"type": "string"},
                               "end": {"type": "string"}},
                "required": ["label", "start", "end"],
                "additionalProperties": False,
            },
        },
        "calendar_request": {
            "type": ["object", "null"],
            "properties": {
                "kind": {"enum": ["lunar_date", "lunar_month", "tet"]},
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "day": {"type": "integer"},
                "leap": {"type": "boolean"},
            },
            "required": ["kind", "year"],
            "additionalProperties": False,
        },
        "unit": {"type": ["string", "null"]},
        "required_data": {"type": "array", "items": {"type": "string"}},
        "candidate_columns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"table": {"type": "string"}, "column": {"type": "string"},
                               "role": {"type": "string"}},
                "required": ["table", "column", "role"],
                "additionalProperties": False,
            },
        },
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "profile_requests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "column": {"type": "string"},
                    "kind": {"enum": ["categorical", "date", "numeric", "lookup", "key"]},
                    "term": {"type": "string"},
                },
                "required": ["table", "column", "kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer_type", "metric", "time_window", "unresolved", "profile_requests"],
    "additionalProperties": False,
}

SQL_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"enum": ["ok", "unanswerable", "abstain"]},
        "sql": {"type": ["string", "null"]},
        "answer_type": {"enum": ANSWER_TYPES + ["unanswerable", "abstain", None]},
        "number_kind": {"enum": ["money", "count", "decimal", None]},
        "date_granularity": {"enum": ["day", "month", None]},
        "reason": {"type": ["string", "null"]},
        "evidence": {
            "type": ["object", "null"],
            "properties": {
                "kind": {"enum": ["readme_absence", "outside_coverage"]},
                "field": {"type": "string"},
                "readme_quote": {"type": "string"},
                "table": {"type": "string"},
                "column": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
            },
            "required": ["kind"],
            "additionalProperties": False,
        },
    },
    "required": ["status", "sql", "answer_type"],
    "additionalProperties": False,
}
