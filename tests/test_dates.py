# -*- coding: utf-8 -*-
"""主数据导入日期规范化看护：统一 年-月-日 补零；带时分秒客观保留。"""
import unittest
from datetime import datetime

from campus.domain.dates import normalize_date_value


class TestNormalizeDateValue(unittest.TestCase):
    def test_datetime_date_only(self):
        self.assertEqual(normalize_date_value(datetime(2026, 1, 5)), "2026-01-05")

    def test_datetime_with_time_kept(self):
        self.assertEqual(normalize_date_value(datetime(2026, 1, 5, 8, 30, 5)),
                         "2026-01-05 08:30:05")

    def test_text_slash(self):
        self.assertEqual(normalize_date_value("2026/1/5"), "2026-01-05")

    def test_text_dot(self):
        self.assertEqual(normalize_date_value("2026.1.5"), "2026-01-05")

    def test_text_chinese(self):
        self.assertEqual(normalize_date_value("2026年1月5日"), "2026-01-05")

    def test_text_dash_no_pad(self):
        self.assertEqual(normalize_date_value("2026-1-5"), "2026-01-05")

    def test_text_with_time(self):
        self.assertEqual(normalize_date_value("2026/1/5 8:30"), "2026-01-05 08:30:00")
        self.assertEqual(normalize_date_value("2026-1-5 08:30:09"), "2026-01-05 08:30:09")

    def test_already_normalized(self):
        self.assertEqual(normalize_date_value("2026-01-05"), "2026-01-05")

    def test_non_date_untouched(self):
        for v in ("13800000001", "浙江大学", "A-123", "", "2026年"):
            self.assertEqual(normalize_date_value(v), v)

    def test_invalid_date_untouched(self):
        self.assertEqual(normalize_date_value("2026-13-45"), "2026-13-45")

    def test_none(self):
        self.assertEqual(normalize_date_value(None), "")


if __name__ == "__main__":
    unittest.main()
