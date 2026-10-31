import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from src.calendar import CalendarResolver
from src.catalog import BusinessCatalog
from src.pipeline import InferencePipeline
from src.test_inference import run_dataset


class FakeLLM:
    def __init__(self):
        self.calls = []

    def infer(self, messages, *, max_tokens=512, temperature=0.0):
        self.calls.append(messages)
        if len(self.calls) % 2:
            return json.dumps({"status": "ok", "answer_type": "number", "number_kind": "money",
                               "metric": "doanh thu", "calendar_request": None})
        return json.dumps({"status": "ok", "answer_type": "number", "number_kind": "money",
                           "sql": 'SELECT SUM(TRY_CAST("amount" AS DOUBLE)) FROM t_csv_orders'})


class InferenceFlowTests(unittest.TestCase):
    def test_runner_writes_answer_from_sql(self):
        with tempfile.TemporaryDirectory() as root:
            dataset = Path(root) / "dataset"
            business = dataset / "data" / "biz_1"
            business.mkdir(parents=True)
            (dataset / "rulebook.md").write_text("Doanh thu là tổng tiền.", encoding="utf-8")
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

    def test_catalog_reads_excel_sqlite_and_rejects_write_sql(self):
        with tempfile.TemporaryDirectory() as root:
            business = Path(root) / "biz"
            business.mkdir()
            (business / "README.md").write_text("sample", encoding="utf-8")
            workbook = Workbook()
            workbook.active.append(["name", "value"])
            workbook.active.append(["A", 3])
            workbook.save(business / "items.xlsx")
            source = sqlite3.connect(business / "sales.sqlite")
            source.execute("CREATE TABLE orders (amount INTEGER)")
            source.execute("INSERT INTO orders VALUES (5)")
            source.commit()
            source.close()
            catalog = BusinessCatalog(business, Path(root) / "catalog.duckdb")
            self.assertEqual(catalog.execute('SELECT "name" FROM t_xlsx_items')[1], [("A",)])
            self.assertEqual(catalog.execute('SELECT "amount" FROM t_sqlite_sales_orders')[1], [("5",)])
            with self.assertRaises(ValueError):
                catalog.execute("DROP TABLE t_xlsx_items")


if __name__ == "__main__":
    unittest.main()
