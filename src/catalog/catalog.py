"""Load CSV, Excel, and SQLite files into temporary DuckDB tables."""

import csv
import re
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from itertools import chain
from pathlib import Path
from typing import Any

import duckdb
from openpyxl import load_workbook
from sqlglot import exp, parse
from sqlglot.dialects.duckdb import DuckDB
from sqlglot.errors import SqlglotError


_MAX_UNIQUE_VALUES = 32


class _DuckDBWithBackticks(DuckDB):
    """Accept model-generated backtick identifiers as well as DuckDB quotes."""

    class Tokenizer(DuckDB.Tokenizer):
        IDENTIFIERS = ['"', "`"]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_name(path: Path, source_table: str | None = None) -> str:
    stem = re.sub(r"_(?:20\d{2}|\d+)$", "", path.stem, flags=re.IGNORECASE)
    text = f"{path.suffix[1:]}_{stem}" + (f"_{source_table}" if source_table else "")
    text = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return "t_" + text


def _columns(headers: Iterable[Any]) -> list[str]:
    used: set[str] = set()
    result = []
    for index, raw in enumerate(headers, start=1):
        base = str(raw).strip() if raw is not None else ""
        base = base or f"col_{index}"
        if base.startswith("__"):
            base = "source_" + base.lstrip("_")
        name = base
        suffix = 2
        while name.casefold() in used or name.startswith("__"):
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name.casefold())
        result.append(name)
    return result


def _cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    text = str(value)
    return text if text.strip() else None


class BusinessCatalog:
    """A disk-backed, queryable catalog for one business directory."""

    def __init__(self, business_dir: Path, database_path: Path) -> None:
        self.business_dir = business_dir
        self.database_path = database_path
        self.readme = (business_dir / "README.md").read_text(encoding="utf-8")
        self.tables: dict[str, dict[str, Any]] = {}
        self._profile_cache: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        self._build()

    def _build(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(self.database_path))
        try:
            for path in sorted(self.business_dir.iterdir()):
                suffix = path.suffix.lower()
                if suffix == ".csv":
                    with path.open(encoding="utf-8-sig", newline="") as stream:
                        self._ingest(conn, _table_name(path), csv.reader(stream), path.name, "")
                elif suffix == ".xlsx":
                    workbook = load_workbook(path, read_only=True, data_only=True)
                    try:
                        for sheet in workbook:
                            self._ingest(conn, _table_name(path), sheet.values, path.name, sheet.title)
                    finally:
                        workbook.close()
                elif suffix in (".sqlite", ".db"):
                    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                    try:
                        names = [row[0] for row in source.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                        )]
                        for name in names:
                            cursor = source.execute(f"SELECT * FROM {_quote(name)}")
                            headers = [column[0] for column in cursor.description]
                            self._ingest(conn, _table_name(path, name), chain([headers], cursor), path.name, name)
                    finally:
                        source.close()
        finally:
            conn.close()

    def _ingest(
        self, conn: duckdb.DuckDBPyConnection, table: str,
        rows: Iterable[Iterable[Any]], file_name: str, sheet_name: str,
    ) -> None:
        iterator = iter(rows)
        headers = next((row for row in iterator if any(cell is not None and str(cell).strip() for cell in row)), None)
        if headers is None:
            return
        columns = _columns(headers)
        if table not in self.tables:
            names = columns + ["__source_file", "__sheet", "__row_index"]
            conn.execute(f"CREATE TABLE {_quote(table)} ("
                         + ", ".join(f"{_quote(name)} VARCHAR" for name in names[:-1])
                         + ', "__row_index" BIGINT)')
            self.tables[table] = {"columns": names, "sources": [], "rows": 0, "samples": {}}
        info = self.tables[table]
        canonical = {name.casefold(): name for name in info["columns"]}
        columns = [canonical.get(name.casefold(), name) for name in columns]
        for name in columns:
            if name.casefold() not in canonical:
                conn.execute(f"ALTER TABLE {_quote(table)} ADD COLUMN {_quote(name)} VARCHAR")
                info["columns"].append(name)
                canonical[name.casefold()] = name
        info["sources"].append({"file": file_name, "sheet": sheet_name})
        insert_cols = columns + ["__source_file", "__sheet", "__row_index"]
        sql = (f"INSERT INTO {_quote(table)} (" + ", ".join(map(_quote, insert_cols))
               + ") VALUES (" + ", ".join("?" for _ in insert_cols) + ")")
        batch: list[list[str | int | None]] = []
        for row_index, row in enumerate(iterator, start=1):
            values = list(row)
            if not any(value is not None and str(value).strip() for value in values):
                continue
            values = [_cell(value) for value in (values + [None] * len(columns))[:len(columns)]]
            for name, value in zip(columns, values):
                if value is not None and name not in info["samples"]:
                    info["samples"][name] = value[:60]
            batch.append(values + [file_name, sheet_name, row_index])
            if len(batch) >= 1000:
                conn.executemany(sql, batch)
                info["rows"] += len(batch)
                batch.clear()
        if batch:
            conn.executemany(sql, batch)
            info["rows"] += len(batch)

    def describe(self) -> str:
        lines = ["Cột dữ liệu là VARCHAR; __row_index là BIGINT và giữ thứ tự dòng gốc trong file/sheet."]
        for table, info in self.tables.items():
            lines.append(f"Bảng {table} ({info['rows']} dòng):")
            for name in info["columns"]:
                sample = info["samples"].get(name)
                type_note = " BIGINT" if name == "__row_index" else ""
                lines.append(f"  {_quote(name)}{type_note}" + (f" — ví dụ {sample!r}" if sample else ""))
            sources = ", ".join(f"{x['file']}:{x['sheet']}" for x in info["sources"][:8])
            lines.append(f"  Nguồn: {sources}")
        return "\n".join(lines)

    def profile(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Inspect only columns selected by the planner, with bounded output."""
        if not isinstance(requests, list):
            return []
        profiles: list[dict[str, Any]] = []
        conn = duckdb.connect(str(self.database_path))
        try:
            conn.execute("SET enable_external_access = false")
            for request in requests[:12]:
                if not isinstance(request, dict):
                    continue
                table = next((name for name in self.tables
                              if name.casefold() == str(request.get("table", "")).casefold()), None)
                column = next((name for name in self.tables[table]["columns"]
                               if name.casefold() == str(request.get("column", "")).casefold()), None) if table else None
                kind = request.get("kind")
                term = str(request.get("term") or "")[:100]
                if (not table or not column or not isinstance(kind, str)
                        or kind not in {"categorical", "date", "numeric", "lookup", "key"}):
                    profiles.append({"request": request, "error": "unknown table, column, or profile kind"})
                    continue
                key = (table, column, kind, term)
                if key not in self._profile_cache:
                    self._profile_cache[key] = self._profile_column(conn, table, column, kind, term)
                profiles.append(self._profile_cache[key])
        finally:
            conn.close()
        return profiles

    @staticmethod
    def _profile_column(conn: duckdb.DuckDBPyConnection, table: str, column: str,
                        kind: str, term: str) -> dict[str, Any]:
        source = _quote(table)
        value = _quote(column)
        counts = conn.execute(
            f"SELECT COUNT(*), COUNT({value}), COUNT(DISTINCT {value}) FROM {source}"
        ).fetchone()
        result: dict[str, Any] = {
            "table": table, "column": column, "kind": kind,
            "rows": counts[0], "non_null": counts[1], "distinct": counts[2],
            "unique_values_complete": counts[2] <= _MAX_UNIQUE_VALUES,
        }
        if result["unique_values_complete"]:
            unique = conn.execute(
                f"SELECT DISTINCT {value} FROM {source} WHERE {value} IS NOT NULL "
                f"ORDER BY {value} LIMIT {_MAX_UNIQUE_VALUES}"
            ).fetchall()
            result["unique_values"] = [row[0] for row in unique]
        if kind == "key":
            samples = conn.execute(
                f"SELECT DISTINCT {value} FROM {source} WHERE {value} IS NOT NULL ORDER BY {value} LIMIT 5"
            ).fetchall()
            cursor = conn.execute(f"SELECT * FROM {source} WHERE {value} IS NULL LIMIT 3")
            names = [item[0] for item in cursor.description]
            row_index_column = names.index("__row_index")
            missing_rows = []
            for row in cursor.fetchall():
                missing_rows.append({name: str(cell)[:80] for name, cell in zip(names, row)
                                     if cell is not None and name != "__row_index"}
                                    | {"__row_index": row[row_index_column]})
            result.update({"samples": [row[0] for row in samples], "missing_key_rows": missing_rows})
        elif kind == "categorical":
            values = conn.execute(
                f"SELECT {value}, COUNT(*) AS n FROM {source} WHERE {value} IS NOT NULL "
                f"GROUP BY {value} ORDER BY n DESC, {value} LIMIT 12"
            ).fetchall()
            result["values"] = [{"value": item, "count": count} for item, count in values]
        elif kind == "lookup":
            if not term:
                result["error"] = "lookup requires a term"
            else:
                rows = conn.execute(
                    f"SELECT {value}, COUNT(*) AS n FROM {source} "
                    f"WHERE CONTAINS(LOWER({value}), LOWER(?)) "
                    f"OR CONTAINS(LOWER(STRIP_ACCENTS({value})), LOWER(STRIP_ACCENTS(?))) "
                    f"GROUP BY {value} ORDER BY n DESC, {value} LIMIT {_MAX_UNIQUE_VALUES + 1}",
                    [term, term],
                ).fetchall()
                result["term"] = term
                result["matches_complete"] = len(rows) <= _MAX_UNIQUE_VALUES
                result["matches"] = [{"value": item, "count": count}
                                     for item, count in rows[:_MAX_UNIQUE_VALUES]]
        elif kind == "date":
            # Sheet names often supply the year when a source cell contains only day/month.
            parsed = (
                f"COALESCE(TRY_CAST({value} AS DATE), "
                f"TRY_CAST(TRY_STRPTIME({value}, '%d/%m/%Y') AS DATE), "
                f"TRY_CAST(TRY_STRPTIME({value}, '%d-%m-%Y') AS DATE), "
                f"TRY_CAST(TRY_STRPTIME({value} || '/' || "
                f"REGEXP_EXTRACT(\"__sheet\", '(20[0-9]{{2}})', 1), '%d/%m/%Y') AS DATE))"
            )
            summary = conn.execute(
                f"SELECT COUNT(d), MIN(d), MAX(d) FROM (SELECT {parsed} AS d FROM {source})"
            ).fetchone()
            result.update({"parsed": summary[0], "min": str(summary[1]) if summary[1] else None,
                           "max": str(summary[2]) if summary[2] else None})
            if not result["unique_values_complete"]:
                samples = conn.execute(
                    f"SELECT DISTINCT {value} FROM {source} WHERE {value} IS NOT NULL "
                    f"ORDER BY {value} LIMIT 6"
                ).fetchall()
                result["samples"] = [row[0] for row in samples]
            sources = conn.execute(
                f"SELECT \"__source_file\", \"__sheet\", COUNT(d), MIN(d), MAX(d) "
                f"FROM (SELECT \"__source_file\", \"__sheet\", {parsed} AS d FROM {source}) "
                f"GROUP BY 1, 2 ORDER BY 1, 2 LIMIT 24"
            ).fetchall()
            result["sources"] = [
                {"file": file, "sheet": sheet, "parsed": count,
                 "min": str(first) if first else None, "max": str(last) if last else None}
                for file, sheet, count, first, last in sources
            ]
        else:
            samples = conn.execute(
                f"SELECT DISTINCT {value} FROM {source} WHERE {value} IS NOT NULL "
                f"ORDER BY {value} LIMIT 8"
            ).fetchall()
            parsed = conn.execute(
                f"SELECT COUNT(TRY_CAST(REPLACE(REPLACE({value}, ',', ''), ' ', '') AS DOUBLE)), "
                f"COUNT(*) FILTER (WHERE CONTAINS({value}, ',')), "
                f"COUNT(*) FILTER (WHERE CONTAINS({value}, '.')) FROM {source}"
            ).fetchone()
            result.update({"samples": [row[0] for row in samples], "parsed_after_removing_commas": parsed[0],
                           "with_comma": parsed[1], "with_dot": parsed[2]})
        return result

    def execute(self, sql: str, *, max_rows: int = 1000) -> tuple[list[str], list[tuple[Any, ...]]]:
        try:
            statements = parse(sql, read=_DuckDBWithBackticks)
        except SqlglotError as exc:
            raise ValueError(f"SQL parse error: {exc}") from exc
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            raise ValueError("SQL must be one read-only SELECT query")
        query = statements[0]
        cte_names = {cte.alias_or_name.casefold() for cte in query.find_all(exp.CTE)}
        allowed = {name.casefold() for name in self.tables} | cte_names
        if any(table.name.casefold() not in allowed for table in query.find_all(exp.Table)):
            raise ValueError("SQL references a table outside this business catalog")
        executable_sql = query.sql(dialect="duckdb") if "`" in sql else sql
        conn = duckdb.connect(str(self.database_path))
        try:
            conn.execute("SET enable_external_access = false")
            result = conn.execute(executable_sql)
            columns = [column[0] for column in result.description]
            rows = result.fetchmany(max_rows + 1)
            if len(rows) > max_rows:
                raise ValueError(f"query returned more than {max_rows} rows")
            return columns, rows
        finally:
            conn.close()
