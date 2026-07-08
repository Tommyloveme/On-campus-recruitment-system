# -*- coding: utf-8 -*-
"""主数据表 Excel 解析：兼容旧 Application 格式与 applicationProcessList 导出格式。"""
import os
import unittest

from campus.core.master_import_config import load_master_import_config
from campus.domain.stage_routing import compute_current_stage
from campus.services.master_import import parse_excel_file
from campus.services.master_import_store import detect_source_key, filename_matches

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESS_LIST = os.path.join(ROOT, "applicationProcessList20260626083908.xlsx")
LEGACY = os.path.join(ROOT, "tests", "fixtures", "master_import", "Application_test.xlsx")


class TestMasterImportParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_master_import_config("registration")
        cls.app_src = next(s for s in cls.cfg["sources"] if s["key"] == "application")

    def test_filename_pattern_accepts_process_list(self):
        cfg = self.cfg
        self.assertTrue(filename_matches("application", "applicationProcessList20260626083908.xlsx", cfg))
        self.assertEqual(detect_source_key("applicationProcessList20260626083908.xlsx", cfg), "application")

    def test_parse_application_process_list(self):
        if not os.path.isfile(PROCESS_LIST):
            self.skipTest("applicationProcessList 样例文件不存在")
        rows = parse_excel_file(PROCESS_LIST, self.app_src)
        valid = [r for r in rows if r.get("phone") and r.get("name")]
        self.assertGreaterEqual(len(valid), 1)
        row = valid[0]
        self.assertTrue(str(row.get("resume_id", "")).startswith("CV"))
        self.assertTrue(str(row.get("phone", "")).isdigit())
        self.assertTrue(str(row.get("current_step", "")).strip())
        compute_current_stage(row, cfg=self.cfg)
        self.assertIn(row.get("current_stage"), {
            "registration", "resume_screening", "tech_interview", "qualification",
            "written_test", "personality_test", "qualification_interview",
            "manager_interview", "approval", "salary", "offer", "contract_signing", "onboarding",
        })

    def test_parse_legacy_application_test(self):
        if not os.path.isfile(LEGACY):
            self.skipTest("Application_test.xlsx 不存在")
        rows = parse_excel_file(LEGACY, self.app_src)
        valid = [r for r in rows if r.get("name")]
        self.assertGreaterEqual(len(valid), 2)
        row = next(r for r in valid if r.get("resume_id") == "RS2026001")
        self.assertEqual(row.get("name"), "主表新人")
        self.assertEqual(row.get("phone"), "13790001001")


if __name__ == "__main__":
    unittest.main()
