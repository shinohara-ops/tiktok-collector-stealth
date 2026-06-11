"""
rules.py の local_skip_reason 内部に視覚的セクションマーカーを挿入する一回限りのスクリプト。

なぜ必要か:
  local_skip_reason は 2029 行の巨大関数で、内部に return が大量に並ぶ。
  判定順は snapshot test 820 ケースで凍結済みなので、return の順序や式は触らない。
  「どこがどのカテゴリの判定か」を読みながら把握するためのコメントだけを差し込む。

挿入規則:
  - 指定行の直前に空行 + ヘッダー + 空行を入れる
  - 行番号は run 前の rules.py の物理行
  - 後ろから挿入することで前方の行番号を保つ

実行後の検証:
  pytest tests/test_rules_snapshot.py -q  → 820 passed
"""
from __future__ import annotations

from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "src" / "tiktok_collector" / "rules.py"


# (元ファイルの該当行, セクションタイトル) のペア。元 grep の Explore マップから採取。
# 行番号は「このセクションが始まる最初の行」。挿入は直前(その行の上)。
SECTIONS: list[tuple[int, str]] = [
    (264,  "類似アカウントの hardcoded ワード(テンプレ/音楽系)"),
    (269,  "未成年系 — 08/09 ペア表記の判定"),
    (278,  "量産系 — ノイズタグ多数 + Bio 同一/空"),
    (300,  "未成年系 — 学校行事/学年/年齢正規表現"),
    (324,  "色付き除外 ID 群(2764 行スナップショット)"),
    (343,  "未成年系 — 08/09 末尾ID + 絵文字 Bio + テンプレ歌"),
    (429,  "未成年系 — 09-08 ペア / シャドバン / CapCut"),
    (523,  "NGワード — \"No bio yet\""),
    (527,  "色付き除外 ID 群(1650 行スナップショット)"),
    (548,  "汎用 色付き除外 v2(リンク/未成年/外国語/ランダムID/fyp/中文/反復ASCII)"),
    (693,  "外国語/海外アカウント — ベトナム/中文/韓国語/英文"),
    (827,  "ノイズ/アイドル/音楽系タグ(daun muda / onephony / 反復ASCII)"),
    (921,  "ベトナム/affiliate/Instagram/メンションのみ Bio + K-POP タグ"),
    (1028, "インドネシア語/マレー語系タグワード"),
    (1109, "ライブ配信/08/09 ハッシュタグトークン"),
    (1198, "非日本語スクリプト + 絵文字のみ Bio + ASCII タグ"),
    (1295, "類似アカウント v1(外部リンク/アダルト/コスプレ/空 Bio + ASCII タグ/ランダム ID)"),
    (1415, "色付き除外 ID 群(1539 行スナップショット)"),
    (1436, "色付き漏れ v2 — ワードリスト + タグコンボ"),
    (1515, "色付き漏れ v1 — ワードリスト + タグコンボ(v2 と部分重複)"),
    (1585, "v5 外国語キーワード + 中文スパム + ベトナム発音記号 + 繁体字"),
    (1627, "追加 NG ワード 1(teamwork/ダンス/推し/アダルト/ファッション)"),
    (1691, "外国語/ベトナム語キーワードリスト + 中文スパム(再掲)"),
    (1724, "追加 NG ワード 2(sexy/感謝/メンションスパム/推し/bot/nidone)"),
    (1774, "フォロワー数チェック(min_followers)"),
    (1783, "AI 生成 ID 形式 + user 接頭辞 + フォロー中 + 広告フラグ + 認証バッジ"),
    (1809, "フォロワー上限超過 + 広告系キーワード"),
    (1835, "公式/法人系キーワード"),
    (1862, "年齢 + 外国語 + 事務所系ワード"),
    (1882, "Live / Music(2000+ アーティスト) / Game / Pet / Food / general NG"),
    (2122, "v5 ハッシュコンボ + 数字のみタグ + 空 Bio/タグ"),
    (2237, "全てパスした → return None"),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    print(f"rules.py 現行行数: {len(lines)}", flush=True)

    # 後ろから挿入(前方の行番号を維持するため)
    inserted = 0
    for raw_line_no, title in sorted(SECTIONS, reverse=True):
        idx = raw_line_no - 1  # 0-based
        if idx < 0 or idx >= len(lines):
            print(f"  [skip] line {raw_line_no} 範囲外", flush=True)
            continue
        header = (
            f"\n"
            f"        # ────────────────────────────────────────────────────────────────\n"
            f"        # SECTION: {title}\n"
            f"        # ────────────────────────────────────────────────────────────────\n"
        )
        lines.insert(idx, header)
        inserted += 1

    TARGET.write_text("".join(lines), encoding="utf-8")
    print(f"挿入したセクションマーカー: {inserted} 個 → 新行数: {sum(1 for _ in TARGET.read_text(encoding='utf-8').splitlines())}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
