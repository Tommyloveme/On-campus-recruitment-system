# -*- coding: utf-8 -*-
"""依赖安装：仅当 requirements.txt 变更时才执行 pip install。"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"
STAMP = ROOT / "venv" / ".requirements.sha256"


def main() -> int:
    if not REQ.is_file():
        print("requirements.txt 不存在", file=sys.stderr)
        return 1
    digest = hashlib.sha256(REQ.read_bytes()).hexdigest()
    if STAMP.is_file() and STAMP.read_text(encoding="utf-8").strip() == digest:
        return 0
    print("安装/更新 Python 依赖…")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", str(REQ)],
        cwd=str(ROOT),
    )
    STAMP.write_text(digest + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
