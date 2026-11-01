"""Grounded planning, targeted profiling, and checked SQL execution."""

import json
from datetime import date
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any

import duckdb

from src.answer import format_answer
from src.calendar import CalendarResolver
from src.catalog import BusinessCatalog
from src.llm.base import BaseLLM
from .schemas import PLAN_OUTPUT_SCHEMA, SQL_OUTPUT_SCHEMA


WINDOW_REPAIR_SCHEMA = {
    "type": "object",
    "properties": {"start": {"type": "string"}, "end": {"type": "string"}},
    "required": ["start", "end"],
    "additionalProperties": False,
}


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


class InvalidPlanWindow(ValueError):
    def __init__(self, field: str, index: int | None, detail: str) -> None:
        self.field = field
        self.index = index
        label = f"{field}[{index}]" if index is not None else field
        super().__init__(f"{label} {detail}")


def _validate_window(window: Any, field: str, index: int | None = None) -> None:
    if not isinstance(window, dict):
        raise InvalidPlanWindow(field, index, "must have start and end dates")
    try:
        start = date.fromisoformat(window["start"])
        end = date.fromisoformat(window["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidPlanWindow(field, index, "must use real YYYY-MM-DD dates") from exc
    if start.isoformat() != window["start"] or end.isoformat() != window["end"]:
        raise InvalidPlanWindow(field, index, "must use YYYY-MM-DD dates")
    if start > end:
        raise InvalidPlanWindow(field, index, "start must not be after end")


def _validate_plan(plan: dict[str, Any]) -> None:
    if not isinstance(plan["profile_requests"], list) or not isinstance(plan["unresolved"], list):
        raise ValueError("stage 1 returned an invalid plan shape")
    if plan.get("answer_type") not in (None, "number", "percent", "string", "date", "boolean", "list", "table"):
        raise ValueError("stage 1 returned an invalid expected answer type")
    if plan["time_window"] is not None:
        _validate_window(plan["time_window"], "time_window")
    comparisons = plan.get("comparison_windows", [])
    if not isinstance(comparisons, list):
        raise ValueError("comparison_windows must be an array")
    for index, window in enumerate(comparisons):
        _validate_window(window, "comparison_windows", index)


def _add_missing_filter_profiles(plan: dict[str, Any], catalog: BusinessCatalog) -> list[dict[str, str]]:
    """Profile real columns named in filters when the planner omitted them."""
    filters = plan.get("filters")
    tables = getattr(catalog, "tables", None)
    if not isinstance(filters, list) or not isinstance(tables, dict):
        return []
    filter_text = " ".join(value for value in filters if isinstance(value, str)).casefold()
    if not filter_text:
        return []
    requests = plan["profile_requests"]
    candidates = plan.get("candidate_columns")
    selected_tables = {
        str(item.get("table", "")).casefold()
        for item in (candidates if isinstance(candidates, list) else []) + requests
        if isinstance(item, dict)
    }
    seen = {
        (str(item.get("table", "")).casefold(), str(item.get("column", "")).casefold())
        for item in requests if isinstance(item, dict)
    }
    added: list[dict[str, str]] = []
    for table, info in tables.items():
        if table.casefold() not in selected_tables:
            continue
        for column in info["columns"]:
            key = (table.casefold(), column.casefold())
            if (len(requests) >= 12 or key in seen or column.startswith("__")
                    or len(column) < 3 or column.casefold() not in filter_text):
                continue
            request = {"table": table, "column": column, "kind": "categorical"}
            requests.append(request)
            added.append(request)
            seen.add(key)
    return added


@dataclass
class PipelineResult:
    record: dict[str, Any]
    trace: dict[str, Any]


class PipelineFailure(ValueError):
    def __init__(self, message: str, trace: dict[str, Any]) -> None:
        super().__init__(message)
        self.trace = trace


class InferencePipeline:
    def __init__(self, llm: BaseLLM, *, max_tokens: int = 4096,
                 stage1_thinking_tokens: int = 1024,
                 stage2_thinking_tokens: int = 2048) -> None:
        if max_tokens < 1 or stage1_thinking_tokens < 0 or stage2_thinking_tokens < 0:
            raise ValueError("token limits must be non-negative and max_tokens must be positive")
        self.llm = llm
        self.max_tokens = max_tokens
        self.stage1_thinking_tokens = stage1_thinking_tokens
        self.stage2_thinking_tokens = stage2_thinking_tokens

    def _thinking_budget(self, target: int) -> int | None:
        # Reserve at least 1024 tokens for the final JSON on normal requests.
        if self.max_tokens <= 1024:
            return None
        budget = min(target, self.max_tokens - 1024)
        return budget if budget > 0 else None

    def run(self, question: dict[str, Any], rulebook: str,
            calendar: CalendarResolver,
            catalog: BusinessCatalog | Callable[[], BusinessCatalog]) -> PipelineResult:
        question_id = question["id"]
        trace: dict[str, Any] = {"question_id": question_id}
        trace["rulebook_chars"] = len(rulebook)
        if callable(catalog):
            catalog = catalog()
        schema = catalog.describe()
        question_context = (
            f"Câu hỏi: {question['question']}\nas_of_date: {question['as_of_date']}\n\n"
            f"Rulebook:\n{rulebook}\n\nREADME công ty:\n{catalog.readme}\n\nSchema SQL:\n{schema}"
        )
        stage1_system_prompt = (
            """Bạn lập kế hoạch tìm dữ liệu để trả lời câu hỏi doanh nghiệp. Suy luận ngắn, không lặp lại; xuất đúng một JSON object, không thêm markdown hay lời giải thích. Đây chưa phải lượt viết SQL hoặc quyết định có trả lời được hay không: không xuất sql, status, unanswerable hoặc abstain, không đoán đáp án.
            Nguồn thông tin: câu hỏi xác định điều người dùng muốn biết; as_of_date là ngày tham chiếu cho các từ như "hôm nay", "tháng này". Rulebook quyết định định nghĩa nghiệp vụ, quy tắc thời gian, điều kiện hợp lệ, đơn vị và cách tính. README công ty giải thích ý nghĩa file, sheet và cột. Schema SQL cho tên bảng/cột thực và một vài giá trị ví dụ; ví dụ không phải danh sách đầy đủ các giá trị. Mọi cột dữ liệu là VARCHAR; __row_index giữ thứ tự dòng gốc. Khi các nguồn chưa đủ rõ, ghi điều chưa rõ vào unresolved, không tự bịa tên cột, giá trị trạng thái hoặc khoảng thời gian.
            Các field JSON cần rút trích:
            - answer_type (bắt buộc): kiểu đáp án dự kiến theo câu hỏi: number, percent, string, date, boolean, list, table; null nếu chưa xác định. Đây là kiểu kết quả, không phải kiểu cột dữ liệu.
            - number_kind: chỉ dùng khi answer_type=number; money cho tiền, count cho số lượng đếm, decimal cho số thực khác; nếu không áp dụng thì null.
            - date_granularity: chỉ dùng khi answer_type=date; day cho YYYY-MM-DD, month cho YYYY-MM; nếu không áp dụng thì null. Kỳ lọc theo tháng không làm đáp án số thành kiểu date.
            - metric (bắt buộc): đại lượng/câu trả lời cần tính hoặc tìm, diễn đạt ngắn theo nghiệp vụ; null nếu câu hỏi không xác định được đại lượng.
            - definitions: mảng chuỗi ghi quy tắc nghiệp vụ ảnh hưởng phép tính, như dòng hợp lệ, dòng cần loại, cách quy đổi đơn vị hoặc cách ghép bảng. Chỉ ghi quy tắc có căn cứ từ câu hỏi, rulebook hoặc README.
            - filters: mảng chuỗi ghi điều kiện lọc theo nghĩa nghiệp vụ (thời gian, đối tượng, trạng thái, chi nhánh...). Chưa biết giá trị trạng thái chính xác thì mô tả ý định lọc và yêu cầu profile cột đó, không đặt ra giá trị giả.
            - time_window (bắt buộc): null nếu không có kỳ dương lịch xác định; nếu có, object {"start":"YYYY-MM-DD","end":"YYYY-MM-DD"} với hai đầu bao gồm. Giải các từ tương đối theo as_of_date và rulebook. Với ngày âm/Tết chưa tra calendar, để null.
            - comparison_windows: mảng object {"label":chuỗi,"start":"YYYY-MM-DD","end":"YYYY-MM-DD"} cho các kỳ phụ khi cần so sánh; [] nếu không có. time_window là kỳ chính.
            - calendar_request: null nếu không cần tra calendar.csv; nếu cần, object có kind=lunar_date (year, month, day, leap), lunar_month (year, month, leap), hoặc tet (year). year là năm âm lịch; leap là boolean, mặc định false. Không tự quy đổi lịch âm.
            - unit: đơn vị của đáp án dự kiến, ví dụ VND, %, đơn, sản phẩm; null khi không có hoặc chưa rõ.
            - required_data: mảng chuỗi mô tả dữ liệu cần cho phép tính, ví dụ ngày phiếu, giá trị phiếu, mã phiếu và trạng thái; ghi theo nghĩa nghiệp vụ kể cả khi chưa tìm được cột.
            - candidate_columns: mảng object {"table":tên bảng,"column":tên cột,"role":vai trò} ánh xạ required_data tới cột có thật trong Schema SQL; [] nếu chưa xác định. role mô tả ngắn như date, measure, filter, key hoặc label. Đây là cột ứng viên cho SQL, không có nghĩa mọi cột đều cần profile.
            - unresolved (bắt buộc): mảng chuỗi nêu chính xác thông tin còn thiếu hoặc mơ hồ cần kiểm tra ở lượt sau; [] nếu không có. Không dùng field này để kết luận unanswerable.
            - profile_requests (bắt buộc): mảng yêu cầu chương trình khám phá giá trị cột TRƯỚC lượt viết SQL. Mỗi phần tử là {"table":tên bảng thật,"column":tên cột thật,"kind":kiểu profile}; riêng kind=lookup cần thêm "term":chuỗi ngắn lấy từ tên đối tượng trong câu hỏi. Không đặt tên cột/file giả; tối đa 12 yêu cầu, không lặp cùng table/column/kind.

            Chọn kind của profile_requests theo điều cần kiểm tra:
            - date: cột thời gian cần biết dạng ngày, số dòng đổi được sang ngày, min/max và phạm vi từng file/sheet; yêu cầu khi câu hỏi có kỳ thời gian hoặc cần chứng cứ phạm vi dữ liệu.
            - numeric: cột tiền/số cần biết ví dụ giá trị, số dòng đổi được sang số và tần suất xuất hiện dấu phẩy/dấu chấm; tự đối chiếu với README trước khi xác định dấu nào là phân cách hàng nghìn hoặc thập phân. Yêu cầu trước khi tính tổng, trung bình hoặc tỷ lệ từ cột VARCHAR.
            - categorical: cột trạng thái/nhóm/loại cần biết các giá trị thực và tần suất để chọn điều kiện lọc; dùng cho giá trị có ít nhóm.
            - lookup: cột tên khách hàng/sản phẩm/đối tượng khi câu hỏi nêu một tên cụ thể; term là một phần tên từ câu hỏi, chương trình tìm các giá trị chứa term không phân biệt hoa/thường hoặc dấu. Không dùng lookup để liệt kê toàn bộ nhóm.
            - key: cột mã phiếu/mã đơn/khóa giao dịch hoặc khóa nối; xem mẫu mã và các dòng thiếu khóa để nhận ra dòng tổng/ghi chú hay cấu trúc nhóm. Chỉ yêu cầu khi khóa giúp đếm, ghép bảng hoặc loại dòng không phải giao dịch.
            Mọi profile trả số dòng, số giá trị khác nhau và unique_values đầy đủ chỉ khi distinct<=32; nếu nhiều hơn, mẫu trả về không đại diện cho toàn bộ dữ liệu. Yêu cầu profile cho các cột trực tiếp quyết định ngày, phép tính, lọc hoặc tính hợp lệ; để [] chỉ khi không cần kiểm tra giá trị cột.

            Giữ các field bắt buộc kể cả khi giá trị là null hoặc []; các field khác chỉ thêm khi có ích. Schema JSON đầu ra:
            """
            + json.dumps(PLAN_OUTPUT_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        )
        first_messages = [
            {"role": "system", "content": stage1_system_prompt},
            {"role": "user", "content": question_context},
        ]
        try:
            first = self.llm.infer(
                first_messages, max_tokens=self.max_tokens, temperature=0.0,
                output_schema=PLAN_OUTPUT_SCHEMA,
                thinking_token_budget=self._thinking_budget(self.stage1_thinking_tokens),
            )
            print("Stage 1 inference returned (plan unchecked)")
            print(first)
            print("="*80)
        except RuntimeError as exc:
            trace["failed_stage"] = "stage1"
            raise PipelineFailure(str(exc), trace) from exc
        trace["stage1_raw"] = first
        try:
            plan = _json_object(first, set(PLAN_OUTPUT_SCHEMA["required"]))
        except ValueError as exc:
            raise PipelineFailure(str(exc), trace) from exc
        try:
            _validate_plan(plan)
        except InvalidPlanWindow as exc:
            trace["stage1_validation_error"] = str(exc)
            original = (plan["time_window"] if exc.index is None
                        else plan["comparison_windows"][exc.index])
            repair_context = {
                "metric": plan.get("metric"), "definitions": plan.get("definitions"),
                "filters": plan.get("filters"), "window_to_fix": original,
            }
            try:
                fixed_text = self.llm.infer([
                    {"role": "system", "content": (
                        "Chỉ sửa start/end của khoảng ngày lỗi. Dùng câu hỏi, as_of_date và rulebook; "
                        "giữ nguyên mọi phần khác của kế hoạch. Trả đúng một JSON object gồm start và end "
                        "là ngày thật dạng YYYY-MM-DD, start <= end."
                    )},
                    {"role": "user", "content": (
                        f"Câu hỏi: {question['question']}\nas_of_date: {question['as_of_date']}\n\n"
                        f"Rulebook:\n{rulebook}\n\nLỗi: {exc}\n\n"
                        "Thông tin kế hoạch liên quan:\n"
                        + json.dumps(repair_context, ensure_ascii=False)
                    )},
                ], max_tokens=min(self.max_tokens, 2048), temperature=0.0,
                    output_schema=WINDOW_REPAIR_SCHEMA,
                    thinking_token_budget=self._thinking_budget(self.stage1_thinking_tokens))
                trace["stage1_repair_raw"] = fixed_text
                print("Stage 1 window repair output:", fixed_text)
                fixed_window = _json_object(fixed_text, {"start", "end"})
                _validate_window(fixed_window, exc.field, exc.index)
                if exc.index is None:
                    plan["time_window"] = fixed_window
                else:
                    plan["comparison_windows"][exc.index] = {
                        **(original if isinstance(original, dict) else {}), **fixed_window,
                    }
                _validate_plan(plan)
            except (RuntimeError, ValueError) as repair_exc:
                trace["stage1_repair_error"] = str(repair_exc)
                raise PipelineFailure(str(repair_exc), trace) from repair_exc
        except ValueError as exc:
            raise PipelineFailure(str(exc), trace) from exc
        auto_profiles = _add_missing_filter_profiles(plan, catalog)
        if auto_profiles:
            trace["auto_profile_requests"] = auto_profiles
        trace["stage1"] = plan
        if plan.get("calendar_request"):
            plan["resolved_calendar_window"] = calendar.resolve(plan["calendar_request"])
            trace["calendar"] = plan["resolved_calendar_window"]
            print(f"Stage 1 resolved calendar window: {plan['resolved_calendar_window']}")

        try:
            profiles = catalog.profile(plan.get("profile_requests", [])) if hasattr(catalog, "profile") else []
        except (ValueError, duckdb.Error) as exc:
            profiles = []
            trace["profile_error"] = f"{type(exc).__name__}: {exc}"
        trace["profiles"] = profiles
        print(f"Stage 1 profile output: {profiles}")
        print("="*80)
        stage2_system_prompt = (
            """Bạn quyết định cách trả lời câu hỏi dữ liệu doanh nghiệp bằng DuckDB. Suy luận ngắn, không lặp lại; xuất đúng một JSON object, không thêm markdown hoặc lời giải thích ngoài JSON. Chương trình sẽ chạy SQL và định dạng kết quả; không tự ghi đáp án tính nhẩm vào JSON.
                Nguồn thông tin: câu hỏi và as_of_date cho mục tiêu, thời điểm tham chiếu; rulebook cho định nghĩa nghiệp vụ và quy tắc tính; README công ty cho ý nghĩa dữ liệu; Schema SQL cho tên bảng/cột thực; Kế hoạch stage 1 là giả thuyết có thể sửa nếu trái câu hỏi hoặc dữ liệu; Profile là kết quả khám phá các cột được chọn. Nếu kế hoạch có resolved_calendar_window, dùng start/end dương lịch đã tra calendar.csv thay cho việc tự đổi ngày âm/Tết. Không bịa cột, trạng thái, giá trị hoặc khoảng thời gian.
                Đọc Profile đúng phạm vi: rows là tổng dòng, non_null là số dòng có giá trị, distinct là số giá trị khác nhau. unique_values chỉ đầy đủ khi unique_values_complete=true; values của categorical chỉ là tối đa 12 nhóm nhiều nhất; samples là mẫu, không chứng minh giá trị khác không tồn tại. lookup.matches chỉ chứa tên khớp term và matches_complete chỉ nói về tập khớp đó. date.parsed/min/max/sources cho biết số ngày đổi được và phạm vi theo file/sheet; numeric.samples/parsed_after_removing_commas/with_comma/with_dot giúp kiểm tra cách ghi số. key.missing_key_rows chỉ là vài dòng thiếu khóa: đối chiếu rulebook/README để phân biệt dòng tổng, ghi chú và dòng giao dịch có ô trống; không tự động loại mọi dòng thiếu khóa. Dữ liệu cột thông thường là VARCHAR; __row_index là BIGINT giữ thứ tự dòng gốc.
                Các field JSON đầu ra:
                - status (bắt buộc): ok nếu có đủ căn cứ tạo SQL; unanswerable chỉ khi có bằng chứng kiểm chứng được về dữ liệu không tồn tại hoặc kỳ hỏi hoàn toàn ngoài phạm vi; abstain nếu thiếu căn cứ để chọn phép tính, cột, giá trị lọc hoặc cách hiểu. Không coi SQL trả 0 dòng là bằng chứng unanswerable.
                - sql (bắt buộc): chuỗi chứa đúng một truy vấn DuckDB SELECT hoặc WITH...SELECT đọc dữ liệu khi status=ok; null khi status=unanswerable/abstain. SQL phải trả trực tiếp giá trị cần nộp, không trả lời bằng văn bản ngoài SQL. Không đọc file, truy cập bảng ngoài Schema SQL, sửa dữ liệu hoặc chạy nhiều câu lệnh.
                - answer_type (bắt buộc): khi ok, chọn number, percent, string, date, boolean, list hoặc table đúng theo câu hỏi; có thể sửa dự kiến của stage 1. Khi unanswerable/abstain, đặt bằng chính status.
                - number_kind: khi answer_type=number, bắt buộc chọn money (tiền, làm tròn số nguyên), count (số lượng nguyên) hoặc decimal (số thực, hai chữ số thập phân); các kiểu khác để null hoặc bỏ qua. SQL phải trả số thực sự, không phải chuỗi đã định dạng.
                - date_granularity: khi answer_type=date, day nếu đáp án YYYY-MM-DD, month nếu đáp án YYYY-MM; các kiểu khác để null hoặc bỏ qua. Kỳ lọc theo tháng không đồng nghĩa đáp án là kiểu date.
                - reason: giải thích ngắn căn cứ của unanswerable hoặc lý do abstain; khi ok để null hoặc bỏ qua. Reason không thay thế evidence.
                - evidence: chỉ có ý nghĩa khi status=unanswerable; object thuộc một trong hai dạng dưới đây. Khi ok/abstain để null hoặc bỏ qua.
                * {"kind":"readme_absence","field":"tên dữ liệu thiếu","readme_quote":"câu trích nguyên văn từ README"}: README phải nói rõ không/thiếu/chưa ghi/trống chính field đó; tên field phải xuất hiện trong câu trích. Chỉ không thấy cột trong Schema SQL chưa đủ để kết luận.
                * {"kind":"outside_coverage","table":"bảng đã profile","column":"cột ngày đã profile","start":"YYYY-MM-DD","end":"YYYY-MM-DD"}: start/end phải đúng một kỳ trong kế hoạch hoặc resolved_calendar_window. Profile date của đúng table/column phải có parsed=non_null>0; cả kỳ hỏi phải nằm trước min hoặc sau max. Nếu kỳ giao một phần phạm vi, tính phần có dữ liệu theo rulebook.
                Nếu không thỏa chính xác một trong hai dạng evidence, chọn abstain. Kỳ trong phạm vi dữ liệu nhưng không có dòng khớp có thể cho kết quả đếm/tổng bằng 0 theo rulebook; xử lý NULL của SUM bằng COALESCE khi 0 là đúng nghĩa nghiệp vụ.

                Quy tắc lập SQL: mỗi lần tham chiếu bảng/cột, kể cả trong hàm và điều kiện WHERE, phải dùng đúng tên trong Schema SQL và đặt trong dấu ngoặc kép; không viết identifier thô. Mọi cột dữ liệu là VARCHAR: đối chiếu mẫu và Profile trước khi chuyển sang số hoặc ngày, chuẩn hóa định dạng theo dữ liệu thực, rồi dùng TRY_CAST hoặc TRY_STRPTIME phù hợp; không CAST trực tiếp chuỗi chưa được kiểm chứng. Dùng literal DATE và so sánh các giá trị cùng kiểu; khoảng thời gian gồm cả hai đầu. Với cột phân loại, ưu tiên giá trị chính xác đã thấy thay vì mẫu LIKE suy đoán. Khi unique_values_complete=true, unique_values là toàn bộ giá trị của cột; mỗi điều kiện lọc chỉ viết một lần, không lặp hoặc tự liệt kê biến thể. Áp dụng điều kiện hợp lệ, dòng cần loại, đơn vị và thứ tự theo rulebook; dùng __row_index khi cần giữ thứ tự gốc hoặc xử lý nhóm dòng.
                Trước khi xuất JSON, tự rà SQL như một câu lệnh DuckDB hoàn chỉnh: đúng một SELECT/WITH...SELECT; tên bảng/cột tồn tại; dấu ngoặc và dấu nháy cân bằng; hàm đủ đối số; mọi phép so sánh đủ hai vế, đúng kiểu; không có điều kiện trùng; kết quả có hình dạng đúng answer_type. Nếu chưa viết được truy vấn đáng tin cậy, chọn abstain.
                Hình dạng kết quả SQL: number/percent/string/date/boolean phải là đúng một ô; percent là số trên thang 0-100, boolean là TRUE/FALSE. list là một cột nhiều dòng hoặc một dòng nhiều cột, sắp xếp theo rulebook. table là bảng với tên cột kết quả thích hợp và số dòng theo dữ liệu thực tế.
                Giữ status, sql và answer_type trong mọi trường hợp. Schema JSON đầu ra:
                """
            + json.dumps(SQL_OUTPUT_SCHEMA, ensure_ascii=False, separators=(",", ":"))
        )
        second_messages = [
            {"role": "system", "content": stage2_system_prompt},
            {"role": "user", "content": (
                question_context + "\n\nKế hoạch:\n" + json.dumps(plan, ensure_ascii=False)
                + "\n\nProfile các cột liên quan:\n" + json.dumps(profiles, ensure_ascii=False, default=str)
                + "\n\nRà SQL trước khi trả JSON: mọi bảng/cột đều có dấu ngoặc kép; "
                  "mọi phép chuyển kiểu khớp giá trị mẫu; điều kiện lọc có căn cứ và không lặp."
            )},
        ]

        try:
            second = self.llm.infer(
                second_messages, max_tokens=self.max_tokens, temperature=0.0,
                output_schema=SQL_OUTPUT_SCHEMA,
                thinking_token_budget=self._thinking_budget(self.stage2_thinking_tokens),
            )
            print("Stage 2 inference returned (SQL unchecked)")
            print(second)
            print("="*80)
        except RuntimeError as exc:
            trace["failed_stage"] = "stage2"
            raise PipelineFailure(str(exc), trace) from exc
        trace["stage2_raw"] = second
        for attempt in range(2):
            sql_plan = None
            try:
                sql_plan = _json_object(second, {"status", "sql", "answer_type"})
                print(f"Stage 2 parsed output: {sql_plan}")

                trace["stage2" if attempt == 0 else "repair"] = sql_plan
                return self._finish(question_id, sql_plan, plan, catalog, profiles, trace)
            except (ValueError, TypeError, duckdb.Error) as exc:
                trace["verification_error"] = f"{type(exc).__name__}: {exc}"
                if attempt:
                    return PipelineResult(format_answer(question_id, "abstain"), trace)
                try:
                    previous_sql = sql_plan.get("sql") if isinstance(sql_plan, dict) else None
                    previous = ("SQL lỗi:\n" + previous_sql[-4000:] if isinstance(previous_sql, str)
                                else "Đoạn cuối phản hồi trước:\n" + second[-1500:])
                    window = plan.get("resolved_calendar_window") or plan.get("time_window")
                    second = self.llm.infer(second_messages + [
                        {"role": "user", "content": (
                            "Kết quả trên không vượt qua kiểm tra: " + str(exc) + ". "
                            + previous + "\nKỳ trong kế hoạch: "
                            + json.dumps(window, ensure_ascii=False) + ". "
                            "Hãy viết lại toàn bộ SQL hợp lệ, không sao chép phần SQL lỗi. "
                            "Đối chiếu Schema SQL và Profile: đặt tên bảng/cột trong dấu ngoặc kép; "
                            "kiểm tra hàm đủ đối số, dấu ngoặc và dấu nháy, điền đủ hai vế của mọi phép so sánh; "
                            "không CAST trực tiếp VARCHAR chưa kiểm chứng; chuyển kiểu theo Profile, "
                            "chỉ dùng giá trị lọc có căn cứ và viết mỗi điều kiện một lần. "
                            "Nếu vẫn không thể trả lời, chọn abstain hoặc unanswerable đúng điều kiện bằng chứng đã nêu. "
                            "Chỉ trả JSON theo cùng schema."
                        )},
                    ], max_tokens=self.max_tokens, temperature=0.0,
                       output_schema=SQL_OUTPUT_SCHEMA,
                       thinking_token_budget=self._thinking_budget(self.stage2_thinking_tokens))
                    trace["repair_raw"] = second
                    print(f"Stage 2 repair output: {second}")
                except RuntimeError as repair_exc:
                    trace["repair_error"] = str(repair_exc)
                    return PipelineResult(format_answer(question_id, "abstain"), trace)
        raise AssertionError("unreachable")

    @staticmethod
    def _unanswerable_supported(sql_plan: dict[str, Any], plan: dict[str, Any],
                                catalog: BusinessCatalog, profiles: list[dict[str, Any]]) -> bool:
        evidence = sql_plan.get("evidence")
        if not isinstance(evidence, dict):
            return False
        if evidence.get("kind") == "readme_absence":
            quote = evidence.get("readme_quote")
            field = evidence.get("field")
            return (isinstance(quote, str) and len(quote) >= 8
                    and isinstance(field, str) and len(field) >= 3
                    and quote.casefold() in catalog.readme.casefold()
                    and field.casefold() in quote.casefold()
                    and any(word in quote.casefold() for word in ("không", "thiếu", "chưa ghi", "trống")))
        if evidence.get("kind") == "outside_coverage":
            try:
                start = date.fromisoformat(evidence["start"])
                end = date.fromisoformat(evidence["end"])
            except (KeyError, TypeError, ValueError):
                return False
            if start > end:
                return False
            def matches_window(value: Any) -> bool:
                if isinstance(value, dict):
                    if value.get("start") == evidence["start"] and value.get("end") == evidence["end"]:
                        return True
                    return any(matches_window(item) for item in value.values())
                if isinstance(value, list):
                    return any(matches_window(item) for item in value)
                return False
            if not matches_window(plan):
                return False
            for profile in profiles:
                if (profile.get("kind") == "date" and profile.get("table") == evidence.get("table")
                        and profile.get("column") == evidence.get("column") and profile.get("parsed", 0) > 0
                        and profile.get("parsed") == profile.get("non_null")
                        and profile.get("min") and profile.get("max")):
                    return end < date.fromisoformat(profile["min"]) or start > date.fromisoformat(profile["max"])
        return False

    def _finish(self, question_id: str, sql_plan: dict[str, Any], plan: dict[str, Any],
                catalog: BusinessCatalog, profiles: list[dict[str, Any]],
                trace: dict[str, Any]) -> PipelineResult:
        if sql_plan["status"] == "unanswerable":
            if sql_plan.get("sql") is not None or sql_plan.get("answer_type") not in (None, "unanswerable"):
                raise ValueError("unanswerable must not include SQL or a concrete answer type")
            if not self._unanswerable_supported(sql_plan, plan, catalog, profiles):
                raise ValueError("unanswerable lacks verified README or date-coverage evidence")
            return PipelineResult(format_answer(question_id, "unanswerable", reason=sql_plan.get("reason")), trace)
        if sql_plan["status"] == "abstain":
            if sql_plan.get("sql") is not None or sql_plan.get("answer_type") not in (None, "abstain"):
                raise ValueError("abstain must not include SQL or a concrete answer type")
            return PipelineResult(format_answer(question_id, "abstain"), trace)
        if sql_plan["status"] != "ok" or not isinstance(sql_plan.get("sql"), str):
            raise ValueError("stage 2 did not return SQL")

        answer_type = sql_plan.get("answer_type") or plan.get("answer_type")
        if answer_type not in ("number", "percent", "string", "date", "boolean", "list", "table"):
            raise ValueError("stage 2 must choose a concrete answer type when status is ok")
        sql = sql_plan["sql"]
        if hasattr(catalog, "normalize_sql"):
            sql = catalog.normalize_sql(sql, profiles)
            if sql != sql_plan["sql"]:
                trace["normalized_sql"] = sql
                print("SQL normalized from schema/profile:", sql)
        columns, rows = catalog.execute(sql)
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
