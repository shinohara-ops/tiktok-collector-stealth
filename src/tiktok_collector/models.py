from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


def _cell(value, limit: int = 180):
    if value is None:
        return ""
    s = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = " ".join(s.split())
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


@dataclass
class Candidate:
    unique_id: str
    display_name: str = ""
    profile_url: str = ""
    post_url: str = ""
    follower_count: Optional[int] = None
    hashtags: str = ""
    signature: str = ""
    caption: str = ""
    screenshot_path: str = ""
    blackband: bool = False
    is_following: bool = False
    is_ad: bool = False
    profile_checked: bool = False
    source: str = "recommend"

    def to_row(self, collector_name: str, reason: str = "", score: str = "", model_used: str = "") -> list:
        return [
            "",
            _cell(collector_name, 80),
            _cell(self.unique_id, 80),
            _cell(self.display_name, 100),
            self.follower_count if self.follower_count is not None else "",
            _cell(self.hashtags, 160),
            _cell((getattr(self, "signature", "") or getattr(self, "bio", "") or getattr(self, "profile_bio", "") or getattr(self, "profile_text", "")), 220),
            _cell(score, 30),
            _cell(reason, 180),
            _cell(model_used, 80),
            _cell(self.profile_url, 220),
            _cell(self.post_url, 260),
            _cell(self.screenshot_path, 220),
        ]

    def dict(self):
        return asdict(self)



# --- follower_count column patch ---
try:
    if not getattr(Candidate, "_follower_count_column_patched", False):
        _original_candidate_to_row = Candidate.to_row

        def _candidate_to_row_with_follower(self, *args, **kwargs):
            row = list(_original_candidate_to_row(self, *args, **kwargs))
            fc = getattr(self, "follower_count", "")
            if fc is not None and fc != "":
                # 既存シートの5列目をフォロワー数列として扱う
                while len(row) <= 4:
                    row.append("")
                row[4] = fc
            return row

        Candidate.to_row = _candidate_to_row_with_follower
        Candidate._follower_count_column_patched = True
except Exception:
    pass
# --- end follower_count column patch ---




# --- feed profile text column patch ---
try:
    if not getattr(Candidate, "_profile_text_column_patched", False):
        _candidate_to_row_before_profile_text = Candidate.to_row

        def _candidate_to_row_with_profile_text(self, *args, **kwargs):
            row = list(_candidate_to_row_before_profile_text(self, *args, **kwargs))
            ptxt = getattr(self, "signature", "") or getattr(self, "bio", "")
            if ptxt:
                while len(row) <= 6:
                    row.append("")
                row[6] = ptxt
            return row

        Candidate.to_row = _candidate_to_row_with_profile_text
        Candidate._profile_text_column_patched = True
except Exception:
    pass
# --- end feed profile text column patch ---



# === 記入者名 強制補完パッチ ===
# run.commandで入力した記入者名を Candidate.to_row の段階で row[1] に入れる。
try:
    import os
    from pathlib import Path

    def _force_get_writer_name():
        name = (
            os.environ.get("TIKTOK_COLLECTOR_NAME")
            or os.environ.get("COLLECTOR_NAME")
            or os.environ.get("SHEET_WRITER_NAME")
            or os.environ.get("WRITER_NAME")
            or ""
        ).strip()
        if name:
            return name

        try:
            here = Path(__file__).resolve()
            candidates = [
                Path.cwd() / ".collector_name",
                here.parents[2] / ".collector_name",
                here.parents[3] / ".collector_name",
            ]
            for p in candidates:
                if p.exists():
                    lines = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                    if lines and lines[0].strip():
                        return lines[0].strip()
        except Exception:
            pass
        return ""

    def _force_should_fill_writer(v):
        s = str(v or "").strip()
        return s == "" or s in ["未設定", "未入力", "None", "none", "null", "-", "ー"]

    if "Candidate" in globals() and not getattr(Candidate, "_force_writer_name_patched", False):
        _candidate_to_row_before_force_writer_name = Candidate.to_row

        def _candidate_to_row_with_force_writer_name(self, *args, **kwargs):
            row = list(_candidate_to_row_before_force_writer_name(self, *args, **kwargs))
            writer = _force_get_writer_name()
            if writer:
                writer_idx = 1
                while len(row) <= writer_idx:
                    row.append("")
                if _force_should_fill_writer(row[writer_idx]):
                    row[writer_idx] = writer
                for attr in ["collector_name", "writer_name", "operator_name", "staff_name"]:
                    try:
                        object.__setattr__(self, attr, writer)
                    except Exception:
                        pass
            return row

        Candidate.to_row = _candidate_to_row_with_force_writer_name
        Candidate._force_writer_name_patched = True

except Exception as _force_writer_name_error:
    print(f"記入者名 強制補完パッチ読み込みエラー: {str(_force_writer_name_error)[:120]}", flush=True)
# === /記入者名 強制補完パッチ ===

