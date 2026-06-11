"""pytest 共通設定。プロジェクトルートと src/ を sys.path に通すだけ。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for p in (PROJECT_ROOT, PROJECT_ROOT / "src"):
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)
