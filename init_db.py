#!/usr/bin/env python3
"""项目根目录入口：执行 scripts/init_db.py（参数原样传递）。"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(ROOT, "scripts", "init_db.py")
raise SystemExit(subprocess.call([sys.executable, SCRIPT] + sys.argv[1:]))
