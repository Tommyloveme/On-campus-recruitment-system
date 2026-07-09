# -*- coding: utf-8 -*-
"""主数据表导入性能基准：用两张真实业务表（各 1 万行）跑完整导入链路。

使用临时数据库，不触碰 data/candidates.db。
    python scripts/benchmark_master_import.py
"""
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(BASE, "tests", "fixtures", "master_import")
FILES = {
    "application": os.path.join(FIXTURE_DIR, "applicationProcessList20260626083908.xlsx"),
    "interview_mgmt": os.path.join(FIXTURE_DIR, "候选人面试安排管理列表20260626083900.xlsx"),
}


def main():
    from campus.core.master_import_config import load_master_import_config
    from campus.db import schema
    from campus.domain.stage_routing import compute_current_stage
    from campus.services.master_import import (
        apply_master_rows,
        merge_rows_by_identity,
        parse_excel_file,
    )

    cfg = load_master_import_config()
    source_map = {s["key"]: s for s in cfg["sources"]}

    t0 = time.perf_counter()
    all_rows = []
    for key, path in FILES.items():
        if key in source_map and os.path.isfile(path):
            rows = parse_excel_file(path, source_map[key])
            print(f"解析 {os.path.basename(path)}: {len(rows)} 行")
            all_rows.extend(rows)
    t_parse = time.perf_counter() - t0

    t0 = time.perf_counter()
    merged = merge_rows_by_identity(all_rows, cfg.get("match_keys"))
    t_merge = time.perf_counter() - t0
    print(f"合并后 {len(merged)} 人")

    with tempfile.TemporaryDirectory() as tmp:
        db = sqlite3.connect(os.path.join(tmp, "bench.db"))
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(schema.SCHEMA)
        schema.migrate(db)

        user = {"display_name": "基准测试"}
        t0 = time.perf_counter()
        created, updated, skipped = apply_master_rows(
            merged, db, cfg, lambda u: True, user, compute_current_stage)
        db.commit()
        t_apply = time.perf_counter() - t0
        db.close()

    print(f"写入：新增 {created} / 更新 {updated} / 跳过 {skipped}")
    print(f"Excel 解析  {t_parse:8.2f}s")
    print(f"行合并      {t_merge:8.2f}s")
    print(f"入库+阶段判定 {t_apply:6.2f}s")
    print(f"总计        {t_parse + t_merge + t_apply:8.2f}s")


if __name__ == "__main__":
    main()
