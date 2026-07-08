# -*- coding: utf-8 -*-
"""候选人数据管道合并看护：主数据优先、双命名空间原始表、总表关联键。

合并结果统一为中文 storage_key（field_store），断言经 field_get 取值。
"""
import unittest

from campus.db.field_store import field_get
from campus.services.candidate_pipeline import master_rule_record, merge_raw_sources
from campus.services.data_hub import NO_RESUME_PREFIX, hub_resume_key


class TestMergePriority(unittest.TestCase):
    def test_master_overrides_non_empty(self):
        manual = {"name": "张三", "school": "手动院校", "note": "手动备注"}
        master = {"school": "主数据院校", "offer_status": "已发放"}
        merged = merge_raw_sources(manual, master)
        self.assertEqual(field_get(merged, "school"), "主数据院校")   # 冲突：主数据优先
        self.assertEqual(field_get(merged, "note"), "手动备注")       # 主数据没有的字段保留手动
        self.assertEqual(field_get(merged, "offer_status"), "已发放")

    def test_master_empty_value_keeps_manual(self):
        merged = merge_raw_sources({"school": "手动院校"}, {"school": ""})
        self.assertEqual(field_get(merged, "school"), "手动院校")

    def test_no_master(self):
        merged = merge_raw_sources({"name": "张三"}, None)
        self.assertEqual(merged, {"name": "张三"})

    def test_dual_namespace_master(self):
        """主数据原始表 {字段键, 字段} 双命名空间（兼容旧 fields）。"""
        master = {"fields": {"school": "浙大"}, "字段": {"毕业院校": "浙大"}}
        merged = merge_raw_sources({"name": "张三"}, master)
        self.assertEqual(field_get(merged, "school"), "浙大")
        self.assertNotIn("字段", merged)

    def test_new_namespace_master(self):
        master = {"字段键": {"毕业院校": "浙大"}, "字段": {"毕业院校": "浙大"}}
        merged = merge_raw_sources({"name": "张三"}, master)
        self.assertEqual(field_get(merged, "school"), "浙大")

    def test_master_rule_record_merges_views(self):
        master = {"fields": {"school": "浙大"}, "字段": {"毕业院校": "浙大"}}
        rec = master_rule_record(master)
        self.assertEqual(rec["school"], "浙大")
        self.assertEqual(rec["毕业院校"], "浙大")

    def test_legacy_flat_master_still_works(self):
        merged = merge_raw_sources({"name": "张三"}, {"school": "浙大"})
        self.assertEqual(field_get(merged, "school"), "浙大")


class TestHubResumeKey(unittest.TestCase):
    def test_with_resume_id(self):
        self.assertEqual(hub_resume_key({"resume_id": "R100", "phone": "138"}), "R100")

    def test_with_chinese_key(self):
        self.assertEqual(hub_resume_key({"简历编号": "R200"}), "R200")

    def test_without_resume_id_uses_phone(self):
        self.assertEqual(hub_resume_key({"phone": "13800000001"}),
                         f"{NO_RESUME_PREFIX}13800000001")

    def test_empty(self):
        self.assertEqual(hub_resume_key({}), "")


if __name__ == "__main__":
    unittest.main()
