# -*- coding: utf-8 -*-
"""模块注册表（全系统唯一数据源）。

系统所有「模块」（左侧导航、权限矩阵的列、阶段写门禁的 key）都在此登记：
- 权限引擎（campus.services.acl）据此解析继承链与有效权限；
- 前端导航（/api/permissions/modules）据此渲染；
- 角色模板（config/roles.json 的 perms）与数据库 module_acl 的 module_key
  必须是本注册表中的 key（campus.core.roles_store 会据此校验）。

新增流程阶段时：在此登记模块 + config/stages/<stage>/ 增加字段配置即可，
无需改动权限引擎或数据库结构。
"""

MODULE_REGISTRY = [
    {"key": "registration", "label": "候选人登记", "type": "item", "parent_key": None},
    {"key": "recruit_flow", "label": "校招流程", "type": "section", "parent_key": None, "items": [
        {"key": "resume_screening", "label": "简历筛选", "type": "item", "parent_key": "recruit_flow"},
        {"key": "qualification", "label": "资格审查", "type": "item", "parent_key": "recruit_flow"},
        {"key": "written_test", "label": "笔试", "type": "item", "parent_key": "recruit_flow"},
        {"key": "personality_test", "label": "性格测评", "type": "item", "parent_key": "recruit_flow"},
        {"key": "qualification_interview", "label": "资格面试", "type": "item", "parent_key": "recruit_flow"},
        {"key": "tech_interview", "label": "技术面", "type": "item", "parent_key": "recruit_flow"},
        {"key": "manager_interview", "label": "主管面", "type": "item", "parent_key": "recruit_flow"},
    ]},
    {"key": "offer_strategy", "label": "Offer策略", "type": "section", "parent_key": None, "items": [
        {"key": "approval", "label": "报批", "type": "item", "parent_key": "offer_strategy"},
        {"key": "salary", "label": "谈薪", "type": "item", "parent_key": "offer_strategy"},
        {"key": "offer", "label": "Offer管理", "type": "item", "parent_key": "offer_strategy"},
        {"key": "contract_signing", "label": "签约情况", "type": "item", "parent_key": "offer_strategy"},
    ]},
    {"key": "onboarding", "label": "入职管理", "type": "item", "parent_key": None},
    {"key": "data_board", "label": "数据看板", "type": "section", "parent_key": None, "items": [
        {"key": "overview", "label": "全局总览", "type": "item", "parent_key": "data_board"},
        {"key": "charts", "label": "数据图表", "type": "item", "parent_key": "data_board"},
    ]},
    {"key": "admin_board", "label": "管理看板", "type": "section", "parent_key": None, "items": [
        {"key": "permissions", "label": "权限管理", "type": "item", "parent_key": "admin_board"},
        {"key": "op_logs", "label": "操作日志", "type": "item", "parent_key": "admin_board"},
        {"key": "backups", "label": "数据备份", "type": "item", "parent_key": "admin_board"},
    ]},
    {"key": "feedback", "label": "问题反馈", "type": "item", "parent_key": None},
]

_MODULE_INDEX = {}


def _build_module_index():
    _MODULE_INDEX.clear()

    def walk(entry, parent_key):
        e = {k: v for k, v in entry.items() if k != "items"}
        e["parent_key"] = parent_key
        _MODULE_INDEX[e["key"]] = e
        for child in entry.get("items", []):
            walk(child, e["key"])

    for entry in MODULE_REGISTRY:
        walk(entry, entry.get("parent_key"))


_build_module_index()


def module_keys():
    return list(_MODULE_INDEX.keys())


def module_entry(key):
    return _MODULE_INDEX.get(key)


def module_ancestor_chain(module_key):
    """模块继承链：自身 → 所属板块 → ...（板块权限下发给子模块）。"""
    chain = []
    seen = set()
    cur = module_key
    while cur and cur in _MODULE_INDEX and cur not in seen:
        seen.add(cur)
        chain.append(cur)
        cur = _MODULE_INDEX[cur].get("parent_key")
    return chain
