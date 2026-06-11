"""
rules.local_skip_reason のスナップショットテスト。

目的:
  Sheets「除外ログ」タブから採取した実データを fixture として固定し、
  リファクタ後も同じ candidate に対して同じ reason 文字列を返すことを保証する。

挙動:
  - tests/fixtures/rules_snapshot/*.json を pytest.parametrize で全部回す
  - 各 fixture 内の各ケースについて Candidate stub を組み立てる
  - local_skip_reason(cand, rules) を呼んで返り値が case["expected_reason"] と完全一致するか assert

NOTE:
  - config.yaml の rules セクションに準ずる stub Rules を使う(Sheets 連動 NG は載せない)
  - candidate には Sheets「除外ログ」に書かれていたフィールドだけを再構築
  - profile_url / post_url は判定に使われないがログ用に渡しておく
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from src.tiktok_collector.rules import local_skip_reason


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "rules_snapshot"
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
    bio: str = ""  # rules.py が signature と bio 両方を見るケースに備える


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
        bio=str(case.get("signature", "")),  # signature と bio を同義として扱う
    )


def _collect_cases() -> list[tuple[str, str, dict]]:
    """(fixture filename, unique_id, case dict) のリストを返す。"""
    out: list[tuple[str, str, dict]] = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        cases = json.loads(path.read_text(encoding="utf-8"))
        for case in cases:
            out.append((path.name, str(case.get("unique_id", "")), case))
    return out


ALL_CASES = _collect_cases()


@pytest.mark.parametrize(
    "fixture_name,unique_id,case",
    ALL_CASES,
    ids=[f"{fn}::{uid}" for fn, uid, _ in ALL_CASES],
)
def test_local_skip_reason_snapshot(fixture_name: str, unique_id: str, case: dict):
    rules = _load_rules_stub()
    cand = _build_candidate(case)
    actual = local_skip_reason(cand, rules)
    expected = case.get("expected_reason")
    assert actual == expected, (
        f"\n--- snapshot mismatch ---\n"
        f"fixture : {fixture_name}\n"
        f"uid     : {unique_id}\n"
        f"expected: {expected!r}\n"
        f"actual  : {actual!r}\n"
        f"hashtags: {case.get('hashtags', '')!r}\n"
        f"sig     : {case.get('signature', '')!r}\n"
        f"display : {case.get('display_name', '')!r}\n"
    )
