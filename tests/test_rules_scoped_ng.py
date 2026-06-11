"""
Sheets 由来のメタ付き NG ワード(scope=hashtag/bio/all、Bio空必須)が
意図通りに発火/不発火することを確認するユニットテスト。

スナップショットテスト(test_rules_snapshot.py)は「Sheets が空のとき」の
挙動を凍結している。こちらはプロバイダにダミーデータを差し込んで、
scope と bio_empty_required の組み合わせを直接検証する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from src.tiktok_collector import rules as rules_module
from src.tiktok_collector.rules import local_skip_reason, set_ng_keyword_meta_provider


@dataclass
class _C:
    unique_id: str = "alice"
    display_name: str = ""
    profile_url: str = ""
    post_url: str = ""
    follower_count: Optional[int] = 500
    hashtags: str = ""
    signature: str = ""
    bio: str = ""
    caption: str = ""


@dataclass
class _R:
    max_followers: int = 2000
    min_followers: int = 0
    ng_keywords: list = field(default_factory=list)
    underage_patterns: list = field(default_factory=list)
    foreign_strict: bool = True


@pytest.fixture
def reset_meta_provider():
    """各テスト後にプロバイダを必ず外す。"""
    yield
    set_ng_keyword_meta_provider(None)


def _set_general_entries(entries: list[dict]) -> None:
    set_ng_keyword_meta_provider(lambda cat: entries if cat == "general" else [])


def test_scope_hashtag_with_bio_empty_required_fires(reset_meta_provider):
    """scope=hashtag, bio_empty_required=True のワードは、Bio が空で
    ハッシュタグに含まれているときにだけ発火する。"""
    _set_general_entries([
        {"word": "可愛", "scope": "hashtag", "bio_empty_required": True, "category": "general"},
    ])
    c = _C(hashtags="#可愛 #ダンス", signature="")
    assert local_skip_reason(c, _R()) == "NGワード(可愛)"


def test_scope_hashtag_with_bio_filled_does_not_fire(reset_meta_provider):
    """同じワード設定でも Bio に何かあれば不発(bio_empty_required=True が効く)。"""
    _set_general_entries([
        {"word": "可愛", "scope": "hashtag", "bio_empty_required": True, "category": "general"},
    ])
    c = _C(hashtags="#可愛 #ダンス", signature="こんにちは")
    result = local_skip_reason(c, _R())
    assert result != "NGワード(可愛)"


def test_scope_bio_matches_only_in_bio(reset_meta_provider):
    """scope=bio のワードは Bio に含まれていれば発火、ハッシュタグだけにあると不発。"""
    _set_general_entries([
        {"word": "secret", "scope": "bio", "bio_empty_required": False, "category": "general"},
    ])
    # ハッシュタグをひらがな入りにして外国語/漢字熟語判定を回避(scope=bio の検証に集中)
    c1 = _C(signature="ひみつのsecretメモ", hashtags="#おはよう")
    assert local_skip_reason(c1, _R()) == "NGワード(secret)"

    # 同じワードでも Bio にはなく、ハッシュタグにだけある場合は scope=bio 由来では発火しない
    c2 = _C(signature="ふつうの紹介文", hashtags="#secret")
    result = local_skip_reason(c2, _R())
    assert result != "NGワード(secret)"


def test_no_provider_means_no_scoped_hit(reset_meta_provider):
    """プロバイダ未登録なら scoped 判定はそもそも動かない。"""
    set_ng_keyword_meta_provider(None)
    c = _C(hashtags="#anything", signature="")
    # 何らかの reason は返るかもしれないが、scoped 由来の特定ワード reason は返らない
    result = local_skip_reason(c, _R())
    assert result is None or "anything" not in (result or "")


def test_provider_returning_empty_does_not_fire(reset_meta_provider):
    """プロバイダが空リストを返すとき、scoped 判定は何もしない。
    既存ハードコード(_colored_tags が "可愛" 単独 + Bio 空)はそのまま動く。"""
    _set_general_entries([])
    c = _C(hashtags="可愛", signature="")  # ハッシュタグ全体が "可愛" 単独で Bio 空
    result = local_skip_reason(c, _R())
    assert result == "ハッシュタグ単体NG(可愛)"
