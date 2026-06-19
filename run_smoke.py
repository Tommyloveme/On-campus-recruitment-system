# -*- coding: utf-8 -*-
import sys
port = sys.argv[1] if len(sys.argv) > 1 else "8002"
code = open("smoke_test.py", encoding="utf-8").read()
code = code.replace('BASE = "http://127.0.0.1:8000"', f'BASE = "http://127.0.0.1:{port}"')
exec(compile(code, "smoke_test.py", "exec"))
