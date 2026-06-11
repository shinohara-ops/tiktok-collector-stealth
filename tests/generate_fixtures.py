"""
Sheets「除外ログ」タブから rules.py のスナップショット用 fixture を作る。

ロジック:
  1. 「除外ログ」タブを全行読み出し
  2. model_used 列が "local:" で始まる行だけ抽出
     (= rules.py の local_skip_reason / blackband など、ローカル判定で弾かれた行)
  3. reason ごとにグループ化し、各 reason から最大 SAMPLE_PER_REASON 件サンプリング
  4. tests/fixtures/rules_snapshot/{slug}.json に保存
     - slug は reason をファイル名安全に変換したもの

このスクリプトは tiktok_collector.config.load_config を通さない(OPENAI_API_KEY 不要)。
verify_ng_setup.py と同じく _SheetsCfgLite を直接組んで SheetsClient に渡す。
"""
from __future__ import annotations

import json
import random
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.tiktok_collector.sheets import SheetsClient  # noqa: E402


SAMPLE_PER_REASON = 3            # 同じ reason 文字列で何件まで採るか
SAMPLE_PER_CATEGORY_CAP = 200    # カテゴリ全体での上限
RANDOM_SEED = 20260611
OUTPUT_DIR = PROJECT_ROOT / "tests" / "fixtures" / "rules_snapshot"
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# reason 文字列の先頭からカテゴリを推定する。先頭一致順。
# どこにも当たらなければ "other" に落とす。
CATEGORY_RULES: list[tuple[str, str]] = [
    ("NGワード", "ng_word"),
    ("未成年系NG", "underage"),
    ("未成年/量産系NG", "underage_mass"),
    ("年齢NG", "age_ng"),
    ("外国語/海外", "foreign"),
    ("量産系NG", "mass_produced"),
    ("ハッシュタグNG", "hashtag_ng"),
    ("ハッシュタグ単体NG", "hashtag_single_ng"),
    ("プロフィール紹介文", "profile_text"),
    ("SNS誘導", "sns_invite"),
    ("ID形式NG", "id_format"),
    ("AI生成系ID", "ai_id"),
    ("ランダムID", "random_id"),
    ("アイドル", "idol_fan"),
]


def _category_of(reason: str) -> str:
    for prefix, slug in CATEGORY_RULES:
        if reason.startswith(prefix):
            return slug
    return "other"


@dataclass
class _SheetsCfgLite:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


# 除外ログ行のカラム位置(models.py の Candidate.to_row に揃える)
COL_TIMESTAMP = 0
COL_COLLECTOR_NAME = 1
COL_UNIQUE_ID = 2
COL_DISPLAY_NAME = 3
COL_FOLLOWER_COUNT = 4
COL_HASHTAGS = 5
COL_SIGNATURE = 6
COL_SCORE = 7
COL_REASON = 8
COL_MODEL_USED = 9
COL_PROFILE_URL = 10
COL_POST_URL = 11
COL_SCREENSHOT_PATH = 12


def _slugify(s: str) -> str:
    # 現状未使用(カテゴリ別ファイル名で代替)。将来的に reason ごとに分けたくなったとき用に残す。
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("/", "_").replace(" ", "_")
    s = re.sub(r"[^\w\-+.,()]", "_", s, flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80] or "untitled"


def _parse_follower(value) -> int | None:
    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if not s:
        return None
    try:
        n = int(float(s))
        return n if 0 <= n < 1_000_000_000 else None
    except ValueError:
        return None


def _load_sheets_client() -> SheetsClient:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    gs = raw.get("google_sheets", {}) or {}
    cfg = _SheetsCfgLite(
        spreadsheet_id=gs["spreadsheet_id"],
        tabs=gs["tabs"],
        auth_mode=gs.get("auth_mode", "oauth"),
        oauth_client_json=gs.get("oauth_client_json", "./credentials/oauth_client.json"),
        oauth_token_json=gs.get("oauth_token_json", "./credentials/token.json"),
        service_account_json=gs.get("service_account_json", "./credentials/service_account.json"),
        ng_keywords_cache_ttl_sec=int(gs.get("ng_keywords_cache_ttl_sec", 600)),
    )
    return SheetsClient(cfg)


def _fetch_skipped_rows(client: SheetsClient) -> list[list]:
    tab = client.tabs.get("skipped")
    if not tab:
        return []
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A2:M",
    ).execute()
    return resp.get("values", []) or []


def _row_to_case(row: list) -> dict | None:
    def at(idx):
        return row[idx] if idx < len(row) else ""
    model_used = str(at(COL_MODEL_USED) or "").strip()
    if not model_used.startswith("local:"):
        return None
    reason = str(at(COL_REASON) or "").strip()
    if not reason:
        return None
    uid = str(at(COL_UNIQUE_ID) or "").strip().lstrip("@")
    if not uid:
        return None
    return {
        "unique_id": uid,
        "display_name": str(at(COL_DISPLAY_NAME) or ""),
        "follower_count": _parse_follower(at(COL_FOLLOWER_COUNT)),
        "hashtags": str(at(COL_HASHTAGS) or ""),
        "signature": str(at(COL_SIGNATURE) or ""),
        "profile_url": str(at(COL_PROFILE_URL) or ""),
        "post_url": str(at(COL_POST_URL) or ""),
        "expected_reason": reason,
        "expected_model_used": model_used,
    }


def main() -> int:
    print("=== rules.py スナップショット fixture 生成 ===", flush=True)
    print(f"出力先: {OUTPUT_DIR}", flush=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = _load_sheets_client()
    rows = _fetch_skipped_rows(client)
    print(f"除外ログ行数: {len(rows)}", flush=True)

    cases_by_reason: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        case = _row_to_case(row)
        if case is None:
            continue
        cases_by_reason[case["expected_reason"]].append(case)

    print(f"local:* で弾かれた reason 種類: {len(cases_by_reason)}", flush=True)
    print(f"local:* 行数合計: {sum(len(v) for v in cases_by_reason.values())}", flush=True)

    # 既存 fixture をクリア(古いカテゴリファイルが残らないように)
    for old in OUTPUT_DIR.glob("*.json"):
        old.unlink()

    rng = random.Random(RANDOM_SEED)

    # reason 単位でまずサンプリング → カテゴリにまとめて、カテゴリ全体の上限でさらに絞る
    per_reason_sampled: list[dict] = []
    for reason, cases in sorted(cases_by_reason.items()):
        sample = cases if len(cases) <= SAMPLE_PER_REASON else rng.sample(cases, SAMPLE_PER_REASON)
        per_reason_sampled.extend(sample)

    by_category: dict[str, list[dict]] = defaultdict(list)
    for case in per_reason_sampled:
        by_category[_category_of(case["expected_reason"])].append(case)

    summary = []
    for category, cases in sorted(by_category.items()):
        if len(cases) > SAMPLE_PER_CATEGORY_CAP:
            cases = rng.sample(cases, SAMPLE_PER_CATEGORY_CAP)
        # ファイル内でも安定順にするため reason→unique_id でソート
        cases.sort(key=lambda c: (c["expected_reason"], c["unique_id"]))
        out_path = OUTPUT_DIR / f"{category}.json"
        out_path.write_text(
            json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        distinct_reasons = len({c["expected_reason"] for c in cases})
        summary.append((category, distinct_reasons, len(cases), out_path.name))

    print()
    print("=== fixture サマリ(カテゴリ別) ===")
    for category, n_reasons, n_cases, fname in summary:
        print(f"  {n_cases:>4} cases / {n_reasons:>4} reasons  {fname}")

    print()
    print(f"完了: {len(summary)} ファイル / 合計 {sum(s[2] for s in summary)} ケース")
    return 0


if __name__ == "__main__":
    sys.exit(main())
