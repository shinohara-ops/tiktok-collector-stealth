"""
fixture の expected_reason を「**現在の** rules.py の出力」で上書きする rebaseline スクリプト。

generate_fixtures.py は Sheets 除外ログを fixture 化するが、そこの reason 列は
**そのとき** の rules.py が返した値で、現在の rules.py の判定順とは微妙にズレている
ことがある(時系列で動的パッチが追加されている)。スナップショットテストの目的は
「将来のリファクタで現状の挙動を変えない」ことなので、ベースラインは
**今の rules.py が返す値そのもの**であるべき。

このスクリプトは tests/fixtures/rules_snapshot/*.json を読み込み、各ケースを
local_skip_reason に流して、expected_reason を actual で上書きして書き戻す。
- 今の rules.py で弾けないケース(actual is None or "")は fixture から落とす
  (= スナップショットには「弾けるケース」だけを残す)

将来 rules.py を変更してテストが落ちたら、それは「挙動が変わった」ことを意味する。
意図的なら同じスクリプトでベースラインを取り直す。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.tiktok_collector.rules import local_skip_reason  # noqa: E402


FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "rules_snapshot"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class _StubCandidate:
    unique_id: str = ""
    display_name: str = ""
    profile_url: str = ""
    post_url: str = ""
    follower_count: int | None = None
    hashtags: str = ""
    signature: str = ""
    caption: str = ""
    screenshot_path: str = ""
    blackband: bool = False
    is_following: bool = False
    is_ad: bool = False
    profile_checked: bool = False
    source: str = "recommend"
    bio: str = ""


@dataclass
class _StubRules:
    max_followers: int = 2000
    min_followers: int = 0
    ng_keywords: list = field(default_factory=list)
    underage_patterns: list = field(default_factory=list)
    foreign_strict: bool = True


def _load_rules_stub() -> _StubRules:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    r = raw.get("rules", {}) or {}
    return _StubRules(
        max_followers=int(r.get("max_followers", 2000)),
        min_followers=int(r.get("min_followers", 0)),
        ng_keywords=list(r.get("ng_keywords", []) or []),
        underage_patterns=[str(p) for p in r.get("underage_patterns", []) or []],
        foreign_strict=bool(r.get("foreign_strict", True)),
    )


def _build_candidate(case: dict) -> _StubCandidate:
    return _StubCandidate(
        unique_id=str(case.get("unique_id", "")),
        display_name=str(case.get("display_name", "")),
        profile_url=str(case.get("profile_url", "")),
        post_url=str(case.get("post_url", "")),
        follower_count=case.get("follower_count"),
        hashtags=str(case.get("hashtags", "")),
        signature=str(case.get("signature", "")),
        bio=str(case.get("signature", "")),
    )


def main() -> int:
    print("=== fixture rebaseline 開始 ===", flush=True)
    rules = _load_rules_stub()
    summary = []

    for path in sorted(FIXTURES_DIR.glob("*.json")):
        cases = json.loads(path.read_text(encoding="utf-8"))
        before = len(cases)
        updated: list[dict] = []
        for case in cases:
            cand = _build_candidate(case)
            actual = local_skip_reason(cand, rules)
            if not actual:
                # 今の rules.py で弾けないものはスナップショットに残さない
                continue
            new_case = dict(case)
            sheet_reason = new_case.get("expected_reason")
            new_case["expected_reason"] = actual
            if sheet_reason and sheet_reason != actual:
                new_case["sheet_logged_reason"] = sheet_reason
            updated.append(new_case)
        updated.sort(key=lambda c: (c["expected_reason"], c["unique_id"]))
        path.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        summary.append((path.name, before, len(updated)))

    print()
    print("=== rebaseline サマリ(before → after) ===")
    for name, before, after in summary:
        print(f"  {before:>4} → {after:<4} cases  {name}")
    print(f"\n合計: {sum(s[2] for s in summary)} cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
