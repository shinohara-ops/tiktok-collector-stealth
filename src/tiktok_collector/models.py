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
        # signature と bio は同じ意味で使われる(rules.py が両方見るため candidate に両方ぶら下がる場合がある)。
        # 順序: signature → bio → profile_bio → profile_text の最初に値があるものを採用。
        profile_text = (
            getattr(self, "signature", "")
            or getattr(self, "bio", "")
            or getattr(self, "profile_bio", "")
            or getattr(self, "profile_text", "")
        )
        return [
            "",
            _cell(collector_name, 80),
            _cell(self.unique_id, 80),
            _cell(self.display_name, 100),
            self.follower_count if self.follower_count is not None else "",
            _cell(self.hashtags, 160),
            _cell(profile_text, 220),
            _cell(score, 30),
            _cell(reason, 180),
            _cell(model_used, 80),
            _cell(self.profile_url, 220),
            _cell(self.post_url, 260),
            _cell(self.screenshot_path, 220),
        ]

    def dict(self):
        return asdict(self)
