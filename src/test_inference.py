"""Run a DataMate dataset through the inference pipeline."""

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from src.answer import format_answer, to_json_line
from src.calendar import CalendarResolver
from src.catalog import BusinessCatalog
from src.pipeline import InferencePipeline


def run_dataset(
    dataset: Path, output: Path, pipeline: InferencePipeline,
    *, limit: int | None = None, debug_dir: Path | None = None,
) -> int:
    """Write one submission line per question and return the processed count."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    rulebook = (dataset / "rulebook.md").read_text(encoding="utf-8")
    calendar = CalendarResolver(dataset / "calendar.csv")
    questions_path = dataset / "questions.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    if debug_dir is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
    processed = 0
    with TemporaryDirectory(prefix="datamate-catalog-") as temp_dir:
        catalogs: dict[str, BusinessCatalog] = {}
        with questions_path.open(encoding="utf-8") as questions, output.open("w", encoding="utf-8") as target:
            for line in questions:
                if limit is not None and processed >= limit:
                    break
                if not line.strip():
                    continue
                question = json.loads(line)
                question_id = question["id"]
                business_id = question["business_id"]
                trace = None
                try:
                    if business_id not in catalogs:
                        business_dir = dataset / "data" / business_id
                        if not business_dir.is_dir():
                            raise FileNotFoundError(f"missing business directory: {business_dir}")
                        catalogs[business_id] = BusinessCatalog(
                            business_dir, Path(temp_dir) / f"{business_id}.duckdb"
                        )
                    result = pipeline.run(question, rulebook, calendar, catalogs[business_id])
                    record, trace = result.record, result.trace
                except Exception as exc:
                    print(f"{question_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
                    record = format_answer(question_id, "abstain")
                    trace = getattr(exc, "trace", {"question_id": question_id})
                    trace["error"] = f"{type(exc).__name__}: {exc}"
                target.write(to_json_line(record))
                target.flush()
                if debug_dir is not None:
                    (debug_dir / f"{question_id}.json").write_text(
                        json.dumps(trace, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                    )
                processed += 1
                print(f"{processed}: {question_id} -> {record['type']}", file=sys.stderr)
    return processed
