# -*- coding: utf-8 -*-
"""通用条件规则引擎（JSON 可配置，纯函数，无 DB 依赖）。

条件节点（可任意嵌套组合）：

组合节点
    {"all": [<节点>, ...]}          全部满足（与）
    {"any": [<节点>, ...]}          任一满足（或）
    {"not": <节点>}                 取反（非）

叶子节点
    {"field": "<字段名>", "op": "<操作符>", "value": <期望值>}
    可选 "table"：指定取数的数据表/命名空间（如 "预处理表"/"主数据原始表"/
    "手动原始表"），省略时使用默认记录。
    field 支持英文 field_key、Excel 中文列名、界面中文标签
    （解析由调用方传入的 resolver 完成，见 build_context_resolver）。

操作符（op，默认 eq）
    eq / ne            等于 / 不等于
    contains           包含（子串）
    icontains          模糊包含（忽略大小写与空白）
    regex              正则匹配（re.search）
    wildcard           通配符匹配（* ?，兼容旧 values 语法）
    in / not_in        在列表中 / 不在列表中
    empty / not_empty  为空 / 非空（无需 value；"*" 等价 not_empty）
    startswith / endswith  前缀 / 后缀
    gt / gte / lt / lte    数值比较（无法转数值时按字符串比较）

用法：
    ok = evaluate(cond, resolver)
    resolver(table, field) -> 字段值字符串
"""
import fnmatch
import re


class RuleConfigError(ValueError):
    """规则 JSON 配置不合法。"""


def _to_text(v):
    return str(v if v is not None else "").strip()


def _to_number(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _compare(op, actual, expected):
    an, en = _to_number(actual), _to_number(expected)
    if an is not None and en is not None:
        a, e = an, en
    else:
        a, e = _to_text(actual), _to_text(expected)
    if op == "gt":
        return a > e
    if op == "gte":
        return a >= e
    if op == "lt":
        return a < e
    return a <= e


def _leaf_matches(op, actual, expected):
    actual = _to_text(actual)
    if op == "eq":
        # 兼容旧 stage_rules 语法："*" 表示任意非空，含 *? 走通配符
        exp = _to_text(expected)
        if exp == "*":
            return bool(actual)
        if "*" in exp or "?" in exp:
            return (fnmatch.fnmatch(actual, exp)
                    or fnmatch.fnmatch(actual.lower(), exp.lower()))
        return actual == exp
    if op == "ne":
        return not _leaf_matches("eq", actual, expected)
    if op == "contains":
        return _to_text(expected) in actual
    if op == "icontains":
        return _to_text(expected).lower().replace(" ", "") in actual.lower().replace(" ", "")
    if op == "regex":
        try:
            return re.search(str(expected), actual) is not None
        except re.error as e:
            raise RuleConfigError(f"正则不合法「{expected}」: {e}")
    if op == "wildcard":
        exp = _to_text(expected)
        return (fnmatch.fnmatch(actual, exp)
                or fnmatch.fnmatch(actual.lower(), exp.lower()))
    if op == "in":
        return actual in [_to_text(x) for x in (expected or [])]
    if op == "not_in":
        return actual not in [_to_text(x) for x in (expected or [])]
    if op == "empty":
        return not actual
    if op == "not_empty":
        return bool(actual)
    if op == "startswith":
        return actual.startswith(_to_text(expected))
    if op == "endswith":
        return actual.endswith(_to_text(expected))
    if op in ("gt", "gte", "lt", "lte"):
        return _compare(op, actual, expected)
    raise RuleConfigError(f"未知操作符「{op}」")


def evaluate(cond, resolver):
    """求值条件节点。resolver(table, field) -> 字段值。"""
    if cond is None:
        return True
    if not isinstance(cond, dict):
        raise RuleConfigError(f"条件节点须为对象: {cond!r}")
    if "all" in cond:
        return all(evaluate(c, resolver) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, resolver) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], resolver)
    field = cond.get("field")
    if not field:
        raise RuleConfigError(f"叶子节点缺少 field: {cond!r}")
    op = cond.get("op", "eq")
    actual = resolver(cond.get("table"), field)
    return _leaf_matches(op, actual, cond.get("value"))


def build_context_resolver(tables, default_table, alias_map=None):
    """构建 resolver。

    tables: {表名: 记录dict}；default_table: 缺省表名；
    alias_map: {中文名/别名: field_key}（兼容旧配置）；
    取值统一经 field_store.field_get，支持 legacy 英文键与中文 storage_key。
    """
    from campus.db.field_store import field_get
    alias_map = alias_map or {}

    def resolver(table, field):
        record = tables.get(table or default_table)
        if record is None:
            raise RuleConfigError(f"未知数据表「{table}」，可用：{'、'.join(tables)}")
        val = field_get(record, field, "")
        if val != "":
            return val
        mapped = alias_map.get(field)
        if mapped is not None:
            return field_get(record, mapped, "")
        return ""

    return resolver


def validate_condition(cond, known_ops=None):
    """静态校验条件节点结构，返回错误列表（不求值）。"""
    errors = []

    def walk(node, path):
        if node is None:
            return
        if not isinstance(node, dict):
            errors.append(f"{path}: 节点须为对象")
            return
        for combo in ("all", "any"):
            if combo in node:
                if not isinstance(node[combo], list):
                    errors.append(f"{path}.{combo}: 须为数组")
                    return
                for i, c in enumerate(node[combo]):
                    walk(c, f"{path}.{combo}[{i}]")
                return
        if "not" in node:
            walk(node["not"], f"{path}.not")
            return
        if not node.get("field"):
            errors.append(f"{path}: 叶子节点缺少 field")
        op = node.get("op", "eq")
        valid = {"eq", "ne", "contains", "icontains", "regex", "wildcard", "in", "not_in",
                 "empty", "not_empty", "startswith", "endswith", "gt", "gte", "lt", "lte"}
        if op not in valid:
            errors.append(f"{path}: 未知操作符「{op}」")
        if op == "regex":
            try:
                re.compile(str(node.get("value") or ""))
            except re.error as e:
                errors.append(f"{path}: 正则不合法 {e}")

    walk(cond, "$")
    return errors
