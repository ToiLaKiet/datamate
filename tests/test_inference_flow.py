import json
from importlib import import_module
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from src.calendar import CalendarResolver
from src.catalog import BusinessCatalog
from src.pipeline import InferencePipeline, PipelineResult
from src.pipeline.pipeline import PipelineFailure
from src.pipeline.schemas import PLAN_OUTPUT_SCHEMA, SQL_OUTPUT_SCHEMA

run_dataset = import_module("src.test-inference").run_dataset


def _plan(**updates):
    return {"answer_type": "number", "metric": "doanh thu", "time_window": None,
            "unresolved": [], "profile_requests": []} | updates


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.options = []

    def infer(self, messages, *, max_tokens=512, temperature=0.0,
              output_schema=None, thinking_token_budget=None):
        self.calls.append(messages)
        self.options.append({"output_schema": output_schema,
                             "thinking_token_budget": thinking_token_budget})
        if len(self.calls) % 2:
            return json.dumps(_plan(number_kind="money", calendar_request=None))
        return json.dumps({"status": "ok", "answer_type": "number", "number_kind": "money",
                           "sql": 'SELECT SUM(TRY_CAST("amount" AS DOUBLE)) FROM t_csv_orders'})


class InferenceFlowTests(unittest.TestCase):
    def test_stage_one_extracts_and_stage_two_can_abstain(self):
        class TwoStageLLM:
            def __init__(self):
                self.responses = iter([
                    _plan(calendar_request=None),
                    {"status": "abstain", "answer_type": "abstain", "sql": None,
                     "reason": "Không chắc về cột dữ liệu"},
                ])
                self.calls = 0

            def infer(self, *args, **kwargs):
                self.calls += 1
                return json.dumps(next(self.responses))

        class MinimalCatalog:
            readme = "Dữ liệu công ty"

            def describe(self):
                return "Bảng công ty"

        llm = TwoStageLLM()
        result = InferencePipeline(llm).run(
            {"id": "q1", "question": "?", "as_of_date": "2026-01-01"},
            "rulebook", None, MinimalCatalog(),
        )
        self.assertEqual(result.record, {"id": "q1", "type": "abstain"})
        self.assertEqual(llm.calls, 2)

    def test_stage_two_marks_verified_missing_data_unanswerable(self):
        class TwoStageLLM:
            responses = iter([
                _plan(number_kind="money"),
                {"status": "unanswerable", "answer_type": "unanswerable", "sql": None,
                 "reason": "README xác nhận không có giá vốn",
                 "evidence": {"kind": "readme_absence", "field": "giá vốn",
                              "readme_quote": "Không ghi giá vốn"}},
            ])

            def infer(self, *args, **kwargs):
                return json.dumps(next(self.responses))

        class MinimalCatalog:
            readme = "Không ghi giá vốn"

            def describe(self):
                return "Không có cột giá vốn"

        result = InferencePipeline(TwoStageLLM()).run(
            {"id": "q2", "question": "Lợi nhuận?", "as_of_date": "2026-01-01"},
            "rulebook", None, MinimalCatalog(),
        )
        self.assertEqual(result.record, {"id": "q2", "type": "unanswerable",
                                         "reason": "README xác nhận không có giá vốn"})

    def test_runner_writes_answer_from_sql(self):
        with tempfile.TemporaryDirectory() as root:
            dataset = Path(root) / "dataset"
            business = dataset / "data" / "biz_1"
            business.mkdir(parents=True)
            (dataset / "rulebook.md").write_text(
                "Doanh thu là tổng tiền.\n## 9. Đáp án và chấm điểm\nGiữ toàn bộ luật.\n",
                encoding="utf-8",
            )
            (dataset / "calendar.csv").write_text(
                "date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n"
                "2026-01-01,4,13,11,2025,false,\n", encoding="utf-8")
            (dataset / "questions.jsonl").write_text(json.dumps({"id": "q1", "business_id": "biz_1",
                "question": "Tổng doanh thu?", "as_of_date": "2026-01-01"}) + "\n", encoding="utf-8")
            (business / "README.md").write_text("orders.amount là tiền bán.", encoding="utf-8")
            (business / "orders.csv").write_text("amount\n100\n250\n", encoding="utf-8")
            output = Path(root) / "submission.jsonl"
            fake = FakeLLM()
            count = run_dataset(dataset, output, InferencePipeline(fake), limit=1)
            self.assertEqual(count, 1)
            self.assertEqual(json.loads(output.read_text()), {"id": "q1", "type": "number", "answer": 350})
            self.assertEqual(len(fake.calls), 2)
            self.assertIn("## 9. Đáp án và chấm điểm", fake.calls[0][1]["content"])
            self.assertIn("orders.amount là tiền bán", fake.calls[0][1]["content"])
            self.assertIn("t_csv_orders", fake.calls[0][1]["content"])
            self.assertEqual(fake.options[0], {"output_schema": PLAN_OUTPUT_SCHEMA,
                                               "thinking_token_budget": 1024})
            self.assertEqual(fake.options[1], {"output_schema": SQL_OUTPUT_SCHEMA,
                                               "thinking_token_budget": 2048})

    def test_runner_keeps_writing_after_abstain(self):
        class StubPipeline:
            def run(self, question, *args):
                record = ({"id": question["id"], "type": "abstain"}
                          if question["id"] == "q1" else
                          {"id": question["id"], "type": "number", "answer": 5})
                return PipelineResult(record, {})

        with tempfile.TemporaryDirectory() as root:
            dataset = Path(root) / "dataset"
            dataset.mkdir()
            (dataset / "rulebook.md").write_text("rulebook", encoding="utf-8")
            (dataset / "calendar.csv").write_text("date,lunar_day,lunar_month,lunar_year,lunar_leap\n",
                                                  encoding="utf-8")
            (dataset / "questions.jsonl").write_text(
                json.dumps({"id": "q1", "business_id": "biz", "question": "?",
                            "as_of_date": "2026-01-01"}) + "\n"
                + json.dumps({"id": "q2", "business_id": "biz", "question": "?",
                              "as_of_date": "2026-01-01"}) + "\n", encoding="utf-8")
            output = Path(root) / "submissions" / "result.jsonl"
            self.assertEqual(run_dataset(dataset, output, StubPipeline()), 2)
            self.assertEqual([json.loads(line) for line in output.read_text().splitlines()], [
                {"id": "q1", "type": "abstain"},
                {"id": "q2", "type": "number", "answer": 5},
            ])

    def test_stage_one_rejects_missing_profile_requests(self):
        class IncompleteLLM:
            calls = 0

            def infer(self, *args, **kwargs):
                self.calls += 1
                return json.dumps({"answer_type": "number", "metric": "doanh thu",
                                   "time_window": None, "unresolved": []})

        class MinimalCatalog:
            readme = "Dữ liệu"

            def describe(self):
                return "Bảng"

        llm = IncompleteLLM()
        with self.assertRaises(PipelineFailure):
            InferencePipeline(llm).run(
                {"id": "q-missing", "question": "Doanh thu?", "as_of_date": "2026-01-01"},
                "rulebook", None, MinimalCatalog(),
            )
        self.assertEqual(llm.calls, 1)

    def test_invalid_stage_one_window_gets_one_repair(self):
        class RepairLLM:
            def __init__(self):
                self.responses = iter([
                    _plan(time_window={"start": "2026-09-01", "end": "2026-2026-09-07"},
                          profile_requests=[{"table": "t_csv_orders", "column": "Tiền", "kind": "numeric"}]),
                    {"start": "2026-09-01", "end": "2026-09-07"},
                    {"status": "abstain", "answer_type": "abstain", "sql": None},
                ])
                self.calls = 0

            def infer(self, *args, **kwargs):
                self.calls += 1
                return json.dumps(next(self.responses))

        class MinimalCatalog:
            readme = "Dữ liệu"

            def describe(self):
                return "Bảng"

        llm = RepairLLM()
        result = InferencePipeline(llm).run(
            {"id": "q-window", "question": "Tháng này?", "as_of_date": "2026-09-07"},
            "rulebook", None, MinimalCatalog(),
        )
        self.assertEqual(llm.calls, 3)
        self.assertEqual(result.trace["stage1"]["time_window"]["end"], "2026-09-07")
        self.assertEqual(result.trace["stage1"]["profile_requests"], [
            {"table": "t_csv_orders", "column": "Tiền", "kind": "numeric"}])
        self.assertIn("stage1_repair_raw", result.trace)

    def test_filter_column_omitted_from_requests_is_profiled(self):
        class FilterLLM:
            def __init__(self):
                self.responses = iter([
                    _plan(
                        filters=["Bỏ phiếu có Trạng thái huỷ"],
                        candidate_columns=[{"table": "t_csv_orders", "column": "Tiền", "role": "measure"}],
                        profile_requests=[{"table": "t_csv_orders", "column": "Tiền", "kind": "numeric"}],
                    ),
                    {"status": "abstain", "answer_type": "abstain", "sql": None},
                ])

            def infer(self, *args, **kwargs):
                return json.dumps(next(self.responses))

        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("Danh sách phiếu.", encoding="utf-8")
            (business / "orders.csv").write_text(
                'Trạng thái,Tiền\nĐã nhập hàng,"1,000"\nĐã huỷ,"2,000"\n', encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            result = InferencePipeline(FilterLLM()).run(
                {"id": "q-filter", "question": "Tổng tiền?", "as_of_date": "2026-09-07"},
                "rulebook", None, catalog,
            )
            self.assertEqual(result.trace["auto_profile_requests"], [
                {"table": "t_csv_orders", "column": "Trạng thái", "kind": "categorical"}])
            status = next(item for item in result.trace["profiles"] if item["column"] == "Trạng thái")
            self.assertEqual(status["unique_values"], ["Đã huỷ", "Đã nhập hàng"])

    def test_schema_profile_normalize_generated_sql(self):
        class SQLLLM:
            def __init__(self):
                self.calls = 0

            def infer(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps(_plan(
                        number_kind="money",
                        time_window={"start": "2026-09-01", "end": "2026-09-07"},
                        profile_requests=[
                            {"table": "t_csv_orders", "column": "Cần trả NCC", "kind": "numeric"},
                            {"table": "t_csv_orders", "column": "Thời gian", "kind": "date"},
                            {"table": "t_csv_orders", "column": "Trạng thái", "kind": "categorical"},
                        ],
                    ))
                return json.dumps({
                    "status": "ok", "answer_type": "number", "number_kind": "money",
                    "sql": ("SELECT SUM(CAST(REPLACE(Cần trả NCC, ',', '') AS BIGINT)) "
                            "FROM t_csv_orders WHERE TRY_CAST(Thời gian AS DATE) "
                            "BETWEEN '2026-09-01' AND '2026-09-07' "
                            "AND Trạng thái = 'Đã nhập hàng'"),
                })

        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("Danh sách phiếu nhập.", encoding="utf-8")
            (business / "orders.csv").write_text(
                'Thời gian,Cần trả NCC,Trạng thái\n'
                '01/09/2026,"1,000",Đã nhập hàng\n'
                '02/09/2026,"2,000",Đã huỷ\n', encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            llm = SQLLLM()
            result = InferencePipeline(llm).run(
                {"id": "q-normalize", "question": "Tiền nhập tháng này?",
                 "as_of_date": "2026-09-07"}, "rulebook", None, catalog,
            )
            self.assertEqual(result.record, {"id": "q-normalize", "type": "number", "answer": 1000})
            self.assertEqual(llm.calls, 2)
            self.assertIn('"Cần trả NCC"', result.trace["normalized_sql"])
            self.assertIn('TRY_STRPTIME("Thời gian"', result.trace["normalized_sql"])
            self.assertEqual(catalog.normalize_sql("SELECT 'Cần trả NCC' AS label FROM t_csv_orders", []),
                             "SELECT 'Cần trả NCC' AS label FROM t_csv_orders")

    def test_profile_is_targeted_and_handles_real_values(self):
        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("Dữ liệu từ tháng 4/2025.", encoding="utf-8")
            (business / "orders.csv").write_text(
                'Mã đơn,Ngày,Trạng thái,Tên hàng,Tiền\n'
                'ORD1,01/04/2025,xong,Cà phê sữa,"1,000"\n'
                'ORD2,02/04/2025,hủy,Trà đào,"2,500"\n'
                'ORD3,03/04/2025,xong,Cà phê sữa,"3,000"\n'
                ',,,Tổng ngày,"6,500"\n', encoding="utf-8",
            )
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            profiles = catalog.profile([
                {"table": "t_csv_orders", "column": "Ngày", "kind": "date"},
                {"table": "t_csv_orders", "column": "Trạng thái", "kind": "categorical"},
                {"table": "t_csv_orders", "column": "Tiền", "kind": "numeric"},
                {"table": "t_csv_orders", "column": "Tên hàng", "kind": "lookup", "term": "ca phe"},
                {"table": "t_csv_orders", "column": "Mã đơn", "kind": "key"},
            ])
            self.assertEqual((profiles[0]["min"], profiles[0]["max"], profiles[0]["parsed"]),
                             ("2025-04-01", "2025-04-03", 3))
            self.assertEqual(profiles[0]["unique_values"],
                             ["01/04/2025", "02/04/2025", "03/04/2025"])
            self.assertEqual(profiles[1]["values"][0], {"value": "xong", "count": 2})
            self.assertEqual(profiles[1]["unique_values"], ["hủy", "xong"])
            self.assertTrue(profiles[1]["unique_values_complete"])
            self.assertEqual(profiles[2]["with_comma"], 4)
            self.assertEqual(len(profiles[2]["unique_values"]), 4)
            self.assertEqual(profiles[3]["matches"], [{"value": "Cà phê sữa", "count": 2}])
            self.assertTrue(profiles[3]["matches_complete"])
            self.assertEqual(profiles[4]["missing_key_rows"][0]["Tên hàng"], "Tổng ngày")
            self.assertEqual(profiles[4]["missing_key_rows"][0]["__row_index"], 4)
            self.assertEqual(catalog.execute(
                '''SELECT SUM(TRY_CAST(REPLACE("Tiền", ',', '') AS BIGINT))
                   FROM t_csv_orders
                   WHERE TRY_STRPTIME("Ngày", '%d/%m/%Y')::DATE
                     BETWEEN DATE '2025-04-01' AND DATE '2025-04-03'
                     AND "Trạng thái" = 'xong' AND "Mã đơn" IS NOT NULL'''
            )[1], [(4000,)])
            self.assertEqual(catalog.execute('SELECT "__row_index" FROM t_csv_orders ORDER BY "__row_index"')[1],
                             [(1,), (2,), (3,), (4,)])
            self.assertEqual(catalog.profile([{"table": "t_csv_orders", "column": "Ngày", "kind": "date"}])[0],
                             profiles[0])

    def test_high_cardinality_profile_marks_values_as_partial(self):
        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("Tên hàng.", encoding="utf-8")
            rows = "Tên hàng\n" + "".join(f"Cà phê {index:02d}\n" for index in range(40))
            (business / "items.csv").write_text(rows, encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            category, lookup = catalog.profile([
                {"table": "t_csv_items", "column": "Tên hàng", "kind": "categorical"},
                {"table": "t_csv_items", "column": "Tên hàng", "kind": "lookup", "term": "ca phe"},
            ])
            self.assertEqual(category["distinct"], 40)
            self.assertFalse(category["unique_values_complete"])
            self.assertNotIn("unique_values", category)
            self.assertEqual(len(category["values"]), 12)
            self.assertFalse(lookup["matches_complete"])
            self.assertEqual(len(lookup["matches"]), 32)

    def test_outside_coverage_requires_profile_evidence(self):
        class ProfileLLM:
            def __init__(self, window, plan_window=None):
                self.calls = 0
                self.window = window
                self.plan_window = plan_window or window

            def infer(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps(_plan(
                        number_kind="money", time_window=self.plan_window,
                        profile_requests=[{"table": "t_csv_orders", "column": "Ngày", "kind": "date"}],
                    ))
                if self.calls == 2:
                    return json.dumps({"status": "unanswerable", "answer_type": "unanswerable",
                                       "sql": None,
                                       "reason": "Ngoài phạm vi dữ liệu",
                                       "evidence": {"kind": "outside_coverage", "table": "t_csv_orders",
                                                    "column": "Ngày", **self.window}})
                return json.dumps({"status": "abstain", "answer_type": "abstain", "sql": None})

        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("Đơn hàng.", encoding="utf-8")
            (business / "orders.csv").write_text("Ngày,Tiền\n01/04/2025,100\n02/04/2025,200\n",
                                                  encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            question = {"id": "q-date", "question": "Doanh thu tháng 3/2025?", "as_of_date": "2025-05-01"}
            outside = ProfileLLM({"start": "2025-03-01", "end": "2025-03-31"})
            result = InferencePipeline(outside).run(question, "rulebook", None, catalog)
            self.assertEqual(result.record["type"], "unanswerable")
            self.assertEqual(outside.calls, 2)
            overlapping = ProfileLLM({"start": "2025-03-31", "end": "2025-04-01"})
            result = InferencePipeline(overlapping).run(question, "rulebook", None, catalog)
            self.assertEqual(result.record["type"], "abstain")
            self.assertEqual(overlapping.calls, 3)
            mismatched = ProfileLLM({"start": "2025-03-01", "end": "2025-03-31"},
                                    {"start": "2025-04-01", "end": "2025-04-30"})
            result = InferencePipeline(mismatched).run(question, "rulebook", None, catalog)
            self.assertEqual(result.record["type"], "abstain")
            self.assertEqual(mismatched.calls, 3)

    def test_sql_error_gets_one_repair_call(self):
        class RepairLLM:
            def __init__(self):
                self.calls = 0

            def infer(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps(_plan(number_kind="money"))
                sql = 'SELECT SUM(TRY_CAST("missing" AS BIGINT)) FROM t_csv_orders' if self.calls == 2 else \
                      'SELECT SUM(TRY_CAST("amount" AS BIGINT)) FROM t_csv_orders'
                return json.dumps({"status": "ok", "answer_type": "number", "number_kind": "money", "sql": sql})

        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("orders.amount là tiền bán.", encoding="utf-8")
            (business / "orders.csv").write_text("amount\n100\n250\n", encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            llm = RepairLLM()
            result = InferencePipeline(llm).run(
                {"id": "q-repair", "question": "Doanh thu?", "as_of_date": "2026-01-01"},
                "rulebook", None, catalog,
            )
            self.assertEqual(result.record, {"id": "q-repair", "type": "number", "answer": 350})
            self.assertEqual(llm.calls, 3)
            self.assertIn("BinderException", result.trace["verification_error"])

    def test_sql_parse_error_gets_one_repair_call(self):
        class RepairLLM:
            def __init__(self):
                self.calls = 0
                self.messages = []

            def infer(self, messages, **kwargs):
                self.calls += 1
                self.messages.append(messages)
                if self.calls == 1:
                    return json.dumps(_plan(number_kind="money"))
                sql = ('SELECT SUM(TRY_CAST(REPLACE("amount") AS BIGINT)) FROM t_csv_orders'
                       if self.calls == 2 else
                       'SELECT SUM(TRY_CAST("amount" AS BIGINT)) FROM t_csv_orders')
                return json.dumps({"status": "ok", "answer_type": "number",
                                   "number_kind": "money", "sql": sql})

        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("orders.amount là tiền bán.", encoding="utf-8")
            (business / "orders.csv").write_text("amount\n100\n250\n", encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            llm = RepairLLM()
            result = InferencePipeline(llm).run(
                {"id": "q-parse", "question": "Doanh thu?", "as_of_date": "2026-01-01"},
                "rulebook", None, catalog,
            )
            self.assertEqual(result.record, {"id": "q-parse", "type": "number", "answer": 350})
            self.assertEqual(llm.calls, 3)
            self.assertIn("SQL parse error", result.trace["verification_error"])
            self.assertIn('SQL lỗi:\nSELECT SUM(TRY_CAST(REPLACE("amount")',
                          llm.messages[2][-1]["content"])
            self.assertIn("điền đủ hai vế", llm.messages[2][-1]["content"])

    def test_row_index_survives_merged_files_with_new_columns(self):
        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("orders", encoding="utf-8")
            (business / "orders_2025.csv").write_text("id,value\nA,1\n", encoding="utf-8")
            (business / "orders_2026.csv").write_text("id,value,note\n,2,Tổng ngày\n", encoding="utf-8")
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            profile = catalog.profile([{"table": "t_csv_orders", "column": "id", "kind": "key"}])[0]
            self.assertEqual(profile["missing_key_rows"][0]["note"], "Tổng ngày")
            self.assertEqual(profile["missing_key_rows"][0]["__row_index"], 1)

    def test_gpu_oom_is_fatal_not_abstain(self):
        class FailingPipeline:
            def run(self, *args):
                raise RuntimeError("[METAL] Insufficient Memory")

        with tempfile.TemporaryDirectory() as root:
            dataset = Path(root) / "dataset"
            dataset.mkdir()
            (dataset / "rulebook.md").write_text("rules", encoding="utf-8")
            (dataset / "calendar.csv").write_text(
                "date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n",
                encoding="utf-8",
            )
            (dataset / "questions.jsonl").write_text(json.dumps({
                "id": "q1", "business_id": "biz_1", "question": "?", "as_of_date": "2026-01-01",
            }) + "\n", encoding="utf-8")
            output = Path(root) / "submission.jsonl"
            with self.assertRaisesRegex(RuntimeError, "GPU hết bộ nhớ"):
                run_dataset(dataset, output, FailingPipeline())
            self.assertEqual(output.read_text(), "")

    def test_catalog_reads_excel_sqlite_and_rejects_write_sql(self):
        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("sample", encoding="utf-8")
            workbook = Workbook()
            workbook.active.title = "04.2025"
            workbook.active.append(["name", "value", "Cần trả NCC", "Ngày"])
            workbook.active.append(["A", 3, "1,000", "01/04"])
            workbook.save(business / "items.xlsx")
            source = sqlite3.connect(business / "sales.sqlite")
            source.execute("CREATE TABLE orders (amount INTEGER)")
            source.execute("INSERT INTO orders VALUES (5)")
            source.commit()
            source.close()
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            self.assertEqual(catalog.execute('SELECT "name" FROM t_xlsx_items')[1], [("A",)])
            self.assertEqual(catalog.execute('SELECT "amount" FROM t_sqlite_sales_orders')[1], [("5",)])
            self.assertEqual(catalog.profile([{"table": "t_xlsx_items", "column": "Ngày", "kind": "date"}])[0]["min"],
                             "2025-04-01")
            self.assertEqual(catalog.execute("SELECT SUM(TRY_CAST(REPLACE(`Cần trả NCC`, ',', '') AS BIGINT)) FROM t_xlsx_items")[1], [(1000,)])
            with self.assertRaisesRegex(ValueError, "outside this business catalog"):
                catalog.execute("SELECT `value` FROM `other_table`")
            with self.assertRaises(ValueError):
                catalog.execute("DROP TABLE t_xlsx_items")


if __name__ == "__main__":
    unittest.main()
