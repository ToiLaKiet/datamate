import json
import unittest
from datetime import date
from decimal import Decimal

from src.answer import format_answer, to_json_line


class AnswerFormatterTests(unittest.TestCase):
    def test_numeric_rules_and_json_types(self):
        money = format_answer("q1", "number", Decimal("12.5"), number_kind="money")
        percent = format_answer("q2", "percent", Decimal("12.345"))
        self.assertEqual(json.loads(to_json_line(money))["answer"], 13)
        self.assertEqual(json.loads(to_json_line(percent))["answer"], 12.35)
        self.assertIsInstance(money["answer"], int)
        with self.assertRaises(ValueError):
            format_answer("q3", "number", "13", number_kind="money")
        with self.assertRaises(ValueError):
            format_answer("q4", "number", 1.5, number_kind="count")

    def test_dates_and_boolean_are_exact_types(self):
        self.assertEqual(format_answer("q1", "date", date(2026, 8, 15))["answer"], "2026-08-15")
        self.assertEqual(format_answer("q2", "date", date(2026, 8, 15), date_granularity="month")["answer"], "2026-08")
        self.assertIs(format_answer("q3", "boolean", False)["answer"], False)
        with self.assertRaises(ValueError):
            format_answer("q4", "boolean", 0)
        with self.assertRaises(ValueError):
            format_answer("q5", "date", "2026-02-30")

    def test_list_order_and_table_shape(self):
        self.assertEqual(format_answer("q1", "list", ["B", "A"])["answer"], ["B", "A"])
        table = {"columns": ["name", "amount"], "rows": [["Chị Lan", Decimal("3200000")]]}
        self.assertEqual(format_answer("q2", "table", table)["answer"]["rows"], [["Chị Lan", 3200000]])
        with self.assertRaises(ValueError):
            format_answer("q3", "table", {"columns": ["name", "amount"], "rows": [["A"]]})

    def test_no_answer_types_omit_answer_field(self):
        self.assertEqual(format_answer("q1", "unanswerable", reason="Thiếu dữ liệu"),
                         {"id": "q1", "type": "unanswerable", "reason": "Thiếu dữ liệu"})
        self.assertEqual(format_answer("q2", "abstain"), {"id": "q2", "type": "abstain"})
        with self.assertRaises(ValueError):
            format_answer("q3", "abstain", 0)


if __name__ == "__main__":
    unittest.main()
