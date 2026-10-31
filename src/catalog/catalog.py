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
    return str(value)


class BusinessCatalog:
    """A disk-backed, queryable catalog for one business directory."""

    def __init__(self, business_dir: Path, database_path: Path) -> None:
        self.business_dir = business_dir
        self.database_path = database_path
        self.readme = (business_dir / "README.md").read_text(encoding="utf-8")
        self.tables: dict[str, dict[str, Any]] = {}
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
            names = columns + ["__source_file", "__sheet"]
            conn.execute(f"CREATE TABLE {_quote(table)} (" + ", ".join(f"{_quote(name)} VARCHAR" for name in names) + ")")
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
        insert_cols = columns + ["__source_file", "__sheet"]
        sql = (f"INSERT INTO {_quote(table)} (" + ", ".join(map(_quote, insert_cols))
               + ") VALUES (" + ", ".join("?" for _ in insert_cols) + ")")
        batch: list[list[str | None]] = []
        for row in iterator:
            values = list(row)
            if not any(value is not None and str(value).strip() for value in values):
                continue
            values = [_cell(value) for value in (values + [None] * len(columns))[:len(columns)]]
            for name, value in zip(columns, values):
                if value is not None and name not in info["samples"]:
                    info["samples"][name] = value[:60]
            batch.append(values + [file_name, sheet_name])
            if len(batch) >= 1000:
                conn.executemany(sql, batch)
                info["rows"] += len(batch)
                batch.clear()
        if batch:
            conn.executemany(sql, batch)
            info["rows"] += len(batch)

    def describe(self) -> str:
        lines = ["Tất cả cột SQL là VARCHAR; dùng TRY_CAST/TRY_STRPTIME khi tính số hoặc ngày."]
        for table, info in self.tables.items():
            lines.append(f"Bảng {table} ({info['rows']} dòng):")
            for name in info["columns"]:
                sample = info["samples"].get(name)
                lines.append(f"  {_quote(name)}" + (f" — ví dụ {sample!r}" if sample else ""))
            sources = ", ".join(f"{x['file']}:{x['sheet']}" for x in info["sources"][:8])
            lines.append(f"  Nguồn: {sources}")
        return "\n".join(lines)

    def execute(self, sql: str, *, max_rows: int = 1000) -> tuple[list[str], list[tuple[Any, ...]]]:
        statements = parse(sql, read="duckdb")
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            raise ValueError("SQL must be one read-only SELECT query")
        query = statements[0]
        cte_names = {cte.alias_or_name.casefold() for cte in query.find_all(exp.CTE)}
        allowed = {name.casefold() for name in self.tables} | cte_names
        if any(table.name.casefold() not in allowed for table in query.find_all(exp.Table)):
            raise ValueError("SQL references a table outside this business catalog")
        conn = duckdb.connect(str(self.database_path))
        try:
            conn.execute("SET enable_external_access = false")
            result = conn.execute(sql)
            columns = [column[0] for column in result.description]
            rows = result.fetchmany(max_rows + 1)
            if len(rows) > max_rows:
                raise ValueError(f"query returned more than {max_rows} rows")
            return columns, rows
        finally:
            conn.close()
