"""Two LLM planning calls followed by deterministic SQL execution."""

import json
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

from src.answer import format_answer
from src.calendar import CalendarResolver
from src.catalog import BusinessCatalog
from src.llm.base import BaseLLM


def _json_object(text: str, required: set[str]) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    candidates = []
    for index, char in enumerate(text):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and required <= value.keys():
                candidates.append(value)
    if not candidates:
        raise ValueError("LLM did not return a complete expected JSON object")
    return candidates[-1]


@dataclass
class PipelineResult:
    record: dict[str, Any]
    trace: dict[str, Any]


class PipelineFailure(ValueError):
    def __init__(self, message: str, trace: dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


class InferencePipeline:
    def __init__(self, llm: BaseLLM, *, max_tokens: int = 2048) -> None:
        self.llm = llm
        self.max_tokens = max_tokens

    def run(self, question: dict[str, Any], rulebook: str,
            calendar: CalendarResolver,
            catalog: BusinessCatalog | Callable[[], BusinessCatalog]) -> PipelineResult:
        question_id = question["id"]
        trace: dict[str, Any] = {"question_id": question_id}
        trace["rulebook_chars"] = len(rulebook)
        try:
            first = self.llm.infer([
            {"role": "system", "content": (
                "Bạn phân tích câu hỏi dữ liệu doanh nghiệp. Chỉ trả một JSON object NGẮN GỌN, tối đa 700 ký tự; "
                "không tạo SQL, không đoán đáp án. Mỗi trường chỉ ghi thông tin có căn cứ, không giải thích dài. "
                "Dùng rulebook làm nguồn luật và as_of_date là hôm nay. JSON gồm: status ('ok' hoặc 'unanswerable'), "
                "answer_type (number/percent/string/date/boolean/list/table), number_kind (money/count/decimal hoặc null), "
                "date_granularity (day/month), metric, definitions, filters, time_window (start/end YYYY-MM-DD hoặc null), "
                "calendar_request (null hoặc object kind=lunar_date/lunar_month/tet với year, month, day, leap khi cần), "
                "unit, required_data, reason. Đưa điều kiện hợp lệ, đơn vị quy đổi và ngoại lệ vào definitions. "
                "Nếu câu hỏi liên quan ngày âm hoặc Tết, yêu cầu tra calendar; không tự tính ngày âm. "
                "Không tự bịa trạng thái đơn, tên cột hay khoảng thời gian không có trong câu hỏi/rulebook. "
                "Để null khi chưa xác định được. README công ty và cột thật sẽ được đưa vào lượt sau."
            )},
            {"role": "user", "content": (
                f"Câu hỏi: {question['question']}\nas_of_date: {question['as_of_date']}\n\nRulebook:\n{rulebook}"
            )},
            ], max_tokens=self.max_tokens, temperature=0.0)
        except RuntimeError as exc:
            trace["failed_stage"] = "stage1"
            raise PipelineFailure(str(exc), trace) from exc
        trace["stage1_raw"] = first
        try:
            plan = _json_object(first, {"status", "answer_type"})
        except ValueError as exc:
            raise PipelineFailure(str(exc), trace) from exc
        trace["stage1"] = plan
        if plan["status"] == "unanswerable":
            return PipelineResult(format_answer(question_id, "unanswerable", reason=plan.get("reason")), trace)
        if plan["status"] != "ok":
            raise ValueError(f"unexpected stage 1 status: {plan['status']}")
        if plan.get("calendar_request"):
            plan["resolved_calendar_window"] = calendar.resolve(plan["calendar_request"])
            trace["calendar"] = plan["resolved_calendar_window"]

        if callable(catalog):
            catalog = catalog()

        try:
            second = self.llm.infer([
            {"role": "system", "content": (
                "Bạn lập truy vấn DuckDB. Chỉ trả một JSON object. Dùng kế hoạch, README và schema thật để chọn bảng/cột. "
                "Chỉ tạo một SELECT hoặc WITH...SELECT; không gọi hàm đọc file hay sửa bảng. Tất cả cột dữ liệu là VARCHAR: "
                "dùng TRY_CAST/TRY_STRPTIME khi tính số/ngày, chú ý dấu phân cách nghìn trong giá trị mẫu. "
                "Dùng khoảng ngày đã giải từ calendar nếu có. Không phỏng đoán cột không có trong schema. "
                "JSON gồm status ('ok' hoặc 'unanswerable'), sql, answer_type, number_kind, date_granularity, reason. "
                "SQL trả đúng giá trị cần nộp: scalar một ô; list một cột nhiều dòng hoặc một dòng nhiều cột; "
                "table nhiều cột nhiều dòng. Sắp xếp list theo rulebook. Percent dùng thang 0-100. "
                "Nếu dữ liệu thiếu thông tin cần thiết, trả status=unanswerable."
            )},
            {"role": "user", "content": (
                "Kế hoạch:\n" + json.dumps(plan, ensure_ascii=False) + "\n\n"
                "README công ty:\n" + catalog.readme + "\n\nSchema SQL:\n" + catalog.describe()
            )},
            ], max_tokens=self.max_tokens, temperature=0.0)
        except RuntimeError as exc:
            trace["failed_stage"] = "stage2"
            raise PipelineFailure(str(exc), trace) from exc
        trace["stage2_raw"] = second
        try:
            sql_plan = _json_object(second, {"status"})
        except ValueError as exc:
            raise PipelineFailure(str(exc), trace) from exc
        trace["stage2"] = sql_plan
        if sql_plan["status"] == "unanswerable":
            return PipelineResult(format_answer(question_id, "unanswerable", reason=sql_plan.get("reason")), trace)
        if sql_plan["status"] != "ok" or not isinstance(sql_plan.get("sql"), str):
            raise ValueError("stage 2 did not return SQL")
        answer_type = sql_plan.get("answer_type", plan["answer_type"])
        if answer_type != plan["answer_type"]:
            raise ValueError("answer type changed between LLM stages")
        columns, rows = catalog.execute(sql_plan["sql"])
        trace["sql_result"] = {"columns": columns, "row_count": len(rows), "preview": rows[:3]}
        if answer_type == "table":
            value: Any = {"columns": columns, "rows": rows}
        elif answer_type == "list":
            if len(rows) == 1 and len(columns) > 1:
                value = list(rows[0])
            elif len(columns) == 1:
                value = [row[0] for row in rows]
            else:
                raise ValueError("list SQL must return one column or one row")
        else:
            if len(rows) != 1 or len(columns) != 1:
                raise ValueError("scalar SQL must return exactly one row and column")
            value = rows[0][0]
        record = format_answer(
            question_id, answer_type, value,
            number_kind=sql_plan.get("number_kind") or plan.get("number_kind"),
            date_granularity=sql_plan.get("date_granularity") or plan.get("date_granularity") or "day",
        )
        return PipelineResult(record, trace)
