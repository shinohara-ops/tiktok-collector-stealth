"""
rules.py 内の hardcoded ワードリストを全部 Sheets に転写する。

戦略:
  1. rules.py を ast でパースし、すべての List リテラル(ast.List)を走査
  2. 全要素が文字列で、かつ uid らしくない(ASCII オンリー + 数字混在の uid を除外)
     リストを NG ワード候補として採用
  3. 周辺の変数名やコメントから category を推定(できなければ general)
  4. seed_ng_keywords.py と同じ重複排除で Sheets に append

備考:
  - 「ノイズタグ」リスト(capcut/fyp/ダンス)は単独 NG ではないため意味が変わる可能性。
    Sheets 投入後に snapshot test が落ちたら、その語の有効列を Sheets で FALSE に
    して挙動を戻せる。
  - 個別 if 文(`if "推し" in bio:` など)に埋め込まれた文字列は ast では拾えない。
    これらは引き続き rules.py 側の hardcoded として動く。
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from src.tiktok_collector.sheets import SheetsClient  # noqa: E402


CONFIG_PATH = PROJECT_ROOT / "config.yaml"
RULES_PATH = PROJECT_ROOT / "src" / "tiktok_collector" / "rules.py"


@dataclass
class _SheetsCfgLite:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


# 変数名にこれらを含むリストは uid リスト扱いでスキップ
SKIP_VAR_PATTERNS = [
    "excluded_ids", "exclude_ids", "uid", "user_id", "_ids_",
    "underage_patterns",  # underage_patterns は yaml で別管理
]


def _load_client() -> SheetsClient:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    gs = raw["google_sheets"]
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


def _read_existing(client: SheetsClient) -> set[tuple[str, str]]:
    tab = client.tabs.get("ng_keywords")
    resp = client.service.spreadsheets().values().get(
        spreadsheetId=client.spreadsheet_id,
        range=f"{tab}!A2:B",
    ).execute()
    existing = set()
    for row in resp.get("values", []) or []:
        if len(row) >= 2:
            cat = str(row[0] or "").strip().lower()
            word = str(row[1] or "").strip().lower()
            if cat and word:
                existing.add((cat, word))
    return existing


def _is_uid_like(item: str) -> bool:
    """uid らしい文字列か。英数字 + _.- のみ で 4-25 文字、数字混在/末尾、または短い"""
    if not item:
        return False
    s = item.strip()
    if len(s) > 30:
        return False
    if not re.fullmatch(r"[a-zA-Z0-9_.\-]+", s):
        return False
    has_digit = any(c.isdigit() for c in s)
    has_separator = any(c in "._-" for c in s)
    # 数字を含み、かつ separator も含むなら uid 度高め
    if has_digit and has_separator:
        return True
    # 末尾が数字 N 桁 以上で、文字数が <=15 なら uid 度高め
    if re.search(r"\d{2,}$", s) and len(s) <= 15:
        return True
    return False


def _list_looks_like_uid_list(items: list[str]) -> bool:
    """リスト全要素を見て uid リストっぽいか判定。"""
    if not items:
        return False
    uid_count = sum(1 for x in items if _is_uid_like(x))
    return uid_count / len(items) >= 0.6  # 6割以上が uid 形なら uid リスト


def _walk_assignments(tree: ast.AST):
    """変数名付きの文字列リテラルリストを yield する。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if not isinstance(node.value, ast.List):
                continue
            items = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    items.append(elt.value)
                else:
                    items = []
                    break
            if items and len(items) >= 2:
                yield (target.id, items, node.lineno)


def _walk_for_iter_lists(tree: ast.AST):
    """`for x in [...]` パターンの無名リストも拾う。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.iter, ast.List):
            items = []
            for elt in node.iter.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    items.append(elt.value)
                else:
                    items = []
                    break
            if items and len(items) >= 2:
                yield ("_anonymous_for_loop", items, node.lineno)


def main() -> int:
    print("=== rules.py 全 NG ワード 転写 ===", flush=True)
    tree = ast.parse(RULES_PATH.read_text(encoding="utf-8"))

    collected: list[tuple[str, int, list[str]]] = []
    for var_name, items, lineno in _walk_assignments(tree):
        if any(p in var_name.lower() for p in SKIP_VAR_PATTERNS):
            continue
        if _list_looks_like_uid_list(items):
            continue
        collected.append((var_name, lineno, items))
    for var_name, items, lineno in _walk_for_iter_lists(tree):
        if _list_looks_like_uid_list(items):
            continue
        collected.append((var_name, lineno, items))

    print(f"発見したリスト数: {len(collected)}", flush=True)
    for var_name, lineno, items in collected:
        print(f"  L{lineno:>5} {var_name}: {len(items)} ワード")

    client = _load_client()
    existing = _read_existing(client)
    print(f"\nSheets 既存ワード行数: {len(existing)}", flush=True)

    rows_to_append: list[list] = []
    for var_name, lineno, items in collected:
        for w in items:
            word = str(w).strip()
            if not word:
                continue
            key = ("general", word.lower())
            if key in existing:
                continue
            existing.add(key)
            memo = f"rules.py L{lineno} {var_name} から転写"
            # 列順: A=カテゴリ B=ワード C=有効 D=適用範囲 E=Bio空必須 F=メモ
            rows_to_append.append([
                "general", word, "TRUE", "all", "FALSE", memo,
            ])

    print(f"追加候補: {len(rows_to_append)} 行", flush=True)
    if not rows_to_append:
        print("追加なし(全て既存)", flush=True)
        return 0

    tab = client.tabs["ng_keywords"]
    # chunked append (Sheets API のリクエストサイズ制限対策)
    CHUNK = 500
    for i in range(0, len(rows_to_append), CHUNK):
        batch = rows_to_append[i:i + CHUNK]
        client.service.spreadsheets().values().append(
            spreadsheetId=client.spreadsheet_id,
            range=f"{tab}!A:F",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": batch},
        ).execute()
        print(f"  ... appended {i + len(batch)} / {len(rows_to_append)}", flush=True)
    print(f"\n追加完了: {len(rows_to_append)} 行", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
