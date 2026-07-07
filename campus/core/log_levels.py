# -*- coding: utf-8 -*-
"""日志等级（唯一数据源）。

规则：数字 1-10，1 为最高权限、10 为最低。
- 每条日志有等级 level：等级越小越敏感（如权限/用户/备份操作为 1）。
- 每个用户有日志权限 users.log_level：只能看到 level >= 自己权限值的日志。
  系统管理员默认 1（全部可见），普通用户默认 10（只见常规业务日志）。
"""

LOG_LEVEL_MIN = 1
LOG_LEVEL_MAX = 10

#: 各动作类型的默认日志等级（未列出的动作默认 10）
DEFAULT_ACTION_LEVELS = {
    "permission": 1,
    "user": 1,
    "backup": 1,
    "config": 3,
    "delete": 5,
    "import": 8,
    "export": 8,
}


def clamp_log_level(value, default=LOG_LEVEL_MAX):
    """把任意输入收敛为合法日志等级（1-10），非法输入返回 default。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(LOG_LEVEL_MIN, min(LOG_LEVEL_MAX, v))


def default_level_for_action(action):
    return DEFAULT_ACTION_LEVELS.get(action, LOG_LEVEL_MAX)
