# -*- coding: utf-8 -*-
"""日期规范化（主数据导入统一入库格式，唯一实现）。

规则：
- 日期统一记录为「YYYY-MM-DD」，月/日两位补零；
- 若原值带时分秒，客观保留为「YYYY-MM-DD HH:MM:SS」（时分秒同样补零）；
- 识别 2026/1/5、2026.1.5、2026年1月5日、2026-1-5 08:30 等常见写法；
- 非日期文本原样返回（不误伤电话、编号等）。
"""
import re
from datetime import datetime

# 年-月-日（分隔符 - / . 年月日），可带 时:分[:秒]
_DATE_RE = re.compile(
    r"^\s*(\d{4})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?"
    r"(?:[\sT]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?\s*$"
)


def normalize_date_value(value):
    """把 datetime 对象或日期样式文本规范化；无法识别的原样返回字符串。"""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.hour or value.minute or value.second:
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    m = _DATE_RE.match(text)
    if not m:
        return text
    y, mo, d, hh, mm, ss = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d),
                      int(hh or 0), int(mm or 0), int(ss or 0))
    except ValueError:
        return text
    if hh is not None:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%d")
