# -*- coding: utf-8 -*-
"""规则引擎看护：与/或/非组合、正则、包含、模糊包含、中文列名、指定数据表。"""
import unittest

from campus.domain.rule_engine import (
    RuleConfigError,
    build_context_resolver,
    evaluate,
    validate_condition,
)


def make_resolver(record, aliases=None, tables=None):
    all_tables = {"预处理表": record}
    all_tables.update(tables or {})
    return build_context_resolver(all_tables, "预处理表", alias_map=aliases or {})


class TestLeafOps(unittest.TestCase):
    def setUp(self):
        self.r = make_resolver({
            "offer_status": "已发放",
            "school": "浙江大学",
            "score": "85",
            "note": "",
        })

    def _ok(self, cond):
        self.assertTrue(evaluate(cond, self.r), cond)

    def _no(self, cond):
        self.assertFalse(evaluate(cond, self.r), cond)

    def test_eq_ne(self):
        self._ok({"field": "offer_status", "op": "eq", "value": "已发放"})
        self._no({"field": "offer_status", "op": "eq", "value": "未发放"})
        self._ok({"field": "offer_status", "op": "ne", "value": "未发放"})

    def test_eq_star_means_not_empty(self):
        self._ok({"field": "offer_status", "op": "eq", "value": "*"})
        self._no({"field": "note", "op": "eq", "value": "*"})

    def test_contains_icontains(self):
        self._ok({"field": "school", "op": "contains", "value": "浙江"})
        self._no({"field": "school", "op": "contains", "value": "北京"})
        self._ok({"field": "school", "op": "icontains", "value": "浙 江"})

    def test_regex(self):
        self._ok({"field": "school", "op": "regex", "value": "(大学|学院)$"})
        self._no({"field": "school", "op": "regex", "value": "^清华"})
        with self.assertRaises(RuleConfigError):
            evaluate({"field": "school", "op": "regex", "value": "([bad"}, self.r)

    def test_wildcard(self):
        self._ok({"field": "school", "op": "wildcard", "value": "浙*大学"})
        self._no({"field": "school", "op": "wildcard", "value": "北*大学"})

    def test_in_not_in(self):
        self._ok({"field": "offer_status", "op": "in", "value": ["已发放", "已接受"]})
        self._ok({"field": "offer_status", "op": "not_in", "value": ["未发放"]})

    def test_empty_not_empty(self):
        self._ok({"field": "note", "op": "empty"})
        self._ok({"field": "school", "op": "not_empty"})

    def test_startswith_endswith(self):
        self._ok({"field": "school", "op": "startswith", "value": "浙江"})
        self._ok({"field": "school", "op": "endswith", "value": "大学"})

    def test_numeric_compare(self):
        self._ok({"field": "score", "op": "gt", "value": 60})
        self._ok({"field": "score", "op": "lte", "value": "85"})
        self._no({"field": "score", "op": "lt", "value": 85})

    def test_unknown_op(self):
        with self.assertRaises(RuleConfigError):
            evaluate({"field": "score", "op": "between", "value": 1}, self.r)


class TestCombinators(unittest.TestCase):
    def setUp(self):
        self.r = make_resolver({"a": "1", "b": "2", "c": ""})

    def test_all_any_not_nested(self):
        cond = {"all": [
            {"field": "a", "op": "eq", "value": "1"},
            {"any": [
                {"field": "b", "op": "eq", "value": "9"},
                {"not": {"field": "c", "op": "not_empty"}},
            ]},
        ]}
        self.assertTrue(evaluate(cond, self.r))

    def test_all_fails_when_one_fails(self):
        cond = {"all": [{"field": "a", "op": "eq", "value": "1"},
                        {"field": "b", "op": "eq", "value": "9"}]}
        self.assertFalse(evaluate(cond, self.r))

    def test_none_condition_is_true(self):
        self.assertTrue(evaluate(None, self.r))


class TestChineseAliasAndTables(unittest.TestCase):
    def test_chinese_field_names(self):
        r = make_resolver({"offer_status": "已发放", "school": "浙江大学"},
                          aliases={"Offer状态": "offer_status", "毕业院校": "school"})
        cond = {"all": [
            {"field": "Offer状态", "op": "eq", "value": "已发放"},
            {"field": "毕业院校", "op": "regex", "value": "大学$"},
        ]}
        self.assertTrue(evaluate(cond, r))

    def test_table_selector(self):
        r = make_resolver({"x": "预处理值"},
                          tables={"主数据原始表": {"目前状态": "Offer中"}})
        self.assertTrue(evaluate(
            {"field": "目前状态", "op": "contains", "value": "Offer", "table": "主数据原始表"}, r))
        with self.assertRaises(RuleConfigError):
            evaluate({"field": "x", "op": "eq", "value": "1", "table": "不存在的表"}, r)

    def test_missing_field_resolves_empty(self):
        r = make_resolver({"a": "1"})
        self.assertTrue(evaluate({"field": "不存在", "op": "empty"}, r))


class TestValidate(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(validate_condition(
            {"all": [{"field": "a", "op": "regex", "value": "x+"}]}), [])

    def test_errors(self):
        errs = validate_condition({"any": [{"op": "eq"}, {"field": "a", "op": "nope"}]})
        self.assertEqual(len(errs), 2)


class TestStageRoutingIntegration(unittest.TestCase):
    """stage_rules.json 实配看护：状态列 → 阶段（含手动流转覆盖）。"""

    def _stage(self, data):
        from campus.domain.stage_routing import compute_current_stage
        base = {"manager_interview_result": "通过"}
        base.update(data)
        return compute_current_stage(dict(base))

    def test_offer_stage(self):
        self.assertEqual(self._stage({"offer_status": "已发放"}), "approval")

    def test_onboarding(self):
        self.assertEqual(self._stage({"onboarded": "是"}), "approval")

    def test_default_registration(self):
        self.assertEqual(self._stage({"registration_status": "已登记"}), "registration")

    def test_manual_stage_override(self):
        self.assertEqual(
            self._stage({"offer_status": "已发放", "manual_stage": "salary"}), "salary")

    def test_manual_stage_invalid_ignored(self):
        self.assertEqual(
            self._stage({"offer_status": "已发放", "manual_stage": "no_such"}), "approval")

    def test_when_rule_with_chinese_name(self):
        """when 条件树直接用中文列名（经字段映射自动解析）。"""
        from campus.core.master_import_config import load_master_import_config
        from campus.domain.stage_routing import compute_current_stage
        cfg = load_master_import_config()
        cfg = dict(cfg)
        cfg["stage_rules"] = {"rules": [
            {"priority": 100, "stage": "offer",
             "when": {"all": [
                 {"field": "Offer状态", "op": "in", "value": ["已发放", "已接受"]},
                 {"not": {"field": "学历", "op": "eq", "value": "大专"}},
             ]}},
        ]}
        data = {"offer_status": "已接受", "education": "硕士", "manager_interview_result": "通过"}
        self.assertEqual(compute_current_stage(data, cfg=cfg), "approval")
        data2 = {"offer_status": "已接受", "education": "大专", "manager_interview_result": "通过"}
        self.assertEqual(compute_current_stage(data2, cfg=cfg), "registration")

    def test_stage_rules_config_valid(self):
        from campus.domain.stage_routing import validate_stage_rules
        self.assertEqual(validate_stage_rules(), [])


if __name__ == "__main__":
    unittest.main()
