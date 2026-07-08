# -*- coding: utf-8 -*-
"""主数据表 Excel 解析：兼容旧 Application 格式与真实业务表（applicationProcessList / 候选人面试安排管理列表）。"""
import os
import unittest

from campus.core.master_import_config import load_master_import_config
from campus.domain.stage_routing import compute_current_stage
from campus.db.field_store import field_get
from campus.services.master_import import join_master_rows, merge_rows_by_identity, parse_excel_file
from campus.services.master_import_store import detect_source_key, filename_matches
from scripts.expand_real_process_status_excels import CASES as REAL_STATUS_CASES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROCESS_LIST = os.path.join(ROOT, "applicationProcessList20260626083908.xlsx")
INTERVIEW_LIST = os.path.join(ROOT, "候选人面试安排管理列表20260626083900.xlsx")
LEGACY = os.path.join(ROOT, "tests", "fixtures", "master_import", "Application_test.xlsx")
FIXTURE_INTERVIEW = os.path.join(ROOT, "tests", "fixtures", "master_import", "候选人面试安排管理列表_test.xlsx")


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
        stage = field_get(row, "current_stage")
        self.assertIn(stage, {
            "registration", "resume_screening", "tech_interview", "qualification",
            "written_test", "personality_test", "qualification_interview",
            "manager_interview", "approval", "salary", "offer", "contract_signing", "onboarding",
        })

    def test_parse_interview_mgmt_list(self):
        if not os.path.isfile(INTERVIEW_LIST):
            self.skipTest("候选人面试安排管理列表样例文件不存在")
        cfg = self.cfg
        self.assertEqual(
            detect_source_key("候选人面试安排管理列表20260626083900.xlsx", cfg), "interview_mgmt")
        src = next(s for s in cfg["sources"] if s["key"] == "interview_mgmt")
        rows = parse_excel_file(INTERVIEW_LIST, src)
        valid = [r for r in rows if r.get("name")]
        self.assertGreaterEqual(len(valid), 2)
        row = valid[0]
        self.assertTrue(str(row.get("application_archive_id", "")).startswith("SR"))
        self.assertTrue(str(row.get("resume_id", "")).startswith("CV"))
        self.assertTrue(str(row.get("current_step", "")).strip())

    def test_identity_merge_by_archive_id(self):
        """两张真实表通过应聘档案编号唯一化合并；掩码手机号不参与身份匹配。"""
        rows = [
            {"application_archive_id": "SR1", "resume_id": "CV1", "name": "甲",
             "phone": "13000000001"},
            {"application_archive_id": "SR1", "resume_id": "CV1", "name": "甲",
             "phone": "+86 XXXXXXXXXXX", "interview_progress": "专业面试"},
            {"application_archive_id": "SR2", "resume_id": "CV2", "name": "乙",
             "phone": "+86 XXXXXXXXXXX"},
        ]
        merged = merge_rows_by_identity(rows)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].get("interview_progress"), "专业面试")
        self.assertEqual(merged[0].get("phone"), "13000000001")

    def test_parse_application_fixture(self):
        if not os.path.isfile(LEGACY):
            self.skipTest("Application_test.xlsx 不存在")
        rows = parse_excel_file(LEGACY, self.app_src)
        valid = [r for r in rows if r.get("name")]
        self.assertGreaterEqual(len(valid), 2)
        row = next(r for r in valid if r.get("resume_id") == "SR2026010100001")
        self.assertEqual(row.get("name"), "主表新人")
        self.assertEqual(row.get("phone"), "13790001001")
        self.assertEqual(row.get("application_archive_id"), "SR2026010100001")

    def test_fixture_dual_excel_covers_process_statuses(self):
        """fixture 双 Excel 导入后覆盖 01-投递 到 10-offer策略。"""
        if not (os.path.isfile(LEGACY) and os.path.isfile(FIXTURE_INTERVIEW)):
            self.skipTest("master_import fixture xlsx 不完整")
        interview_src = next(s for s in self.cfg["sources"] if s["key"] == "interview_mgmt")
        app_rows = parse_excel_file(LEGACY, self.app_src)
        interview_rows = parse_excel_file(FIXTURE_INTERVIEW, interview_src)
        valid = join_master_rows(
            app_rows,
            interview_rows,
            join_key=self.cfg.get("join_key", "application_archive_id"),
            match_keys=self.cfg.get("match_keys"),
        )
        expected = {
            "状态01投递": ("registration", "01-投递"),
            "状态02简历筛选": ("resume_screening", "02-简历筛选"),
            "状态03资格审查": ("qualification", "03-资格审查"),
            "状态04商业秘密签署": ("commercial_secret", "04-商业秘密签署"),
            "状态05笔试": ("written_test", "05-笔试"),
            "状态06性格测评": ("personality_test", "06-性格测评"),
            "状态07资格面试": ("qualification_interview", "07-资格面试"),
            "状态08技术面": ("tech_interview", "08-技术面"),
            "状态09主管面": ("manager_interview", "09-主管面"),
            "状态10offer策略": ("approval", "10-offer策略"),
        }
        by_name = {r.get("name"): r for r in valid}
        self.assertTrue(set(expected).issubset(by_name))
        for name, (stage, status) in expected.items():
            row = by_name[name]
            self.assertEqual(compute_current_stage(row, cfg=self.cfg), stage, name)
            self.assertEqual(field_get(row, "process_status"), status, name)

    def test_real_dual_excel_covers_process_statuses(self):
        """根目录真实双 Excel 扩充后，可通过主数据导入覆盖 01-投递 到 10-offer策略。"""
        if not (os.path.isfile(PROCESS_LIST) and os.path.isfile(INTERVIEW_LIST)):
            self.skipTest("真实主数据双 Excel 不存在")
        interview_src = next(s for s in self.cfg["sources"] if s["key"] == "interview_mgmt")
        app_rows = parse_excel_file(PROCESS_LIST, self.app_src)
        interview_rows = parse_excel_file(INTERVIEW_LIST, interview_src)
        valid = join_master_rows(
            app_rows,
            interview_rows,
            join_key=self.cfg.get("join_key", "application_archive_id"),
            match_keys=self.cfg.get("match_keys"),
        )
        by_name = {r.get("name"): r for r in valid}
        for case in REAL_STATUS_CASES:
            name = case["name"]
            self.assertIn(name, by_name)
            row = by_name[name]
            self.assertEqual(compute_current_stage(row, cfg=self.cfg), case["expected_stage"], name)
            self.assertEqual(field_get(row, "process_status"), case["expected_status"], name)


if __name__ == "__main__":
    unittest.main()
