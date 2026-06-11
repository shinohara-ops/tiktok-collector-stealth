from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


HEADERS = [
    "取得日時", "収集者", "ユーザーID", "表示名", "フォロワー数", "ハッシュタグ",
    "プロフィール紹介文", "可愛さ点数", "理由", "使用モデル", "プロフURL", "投稿URL", "スクショパス",
]

NG_KEYWORDS_HEADERS = ["カテゴリ", "ワード", "有効", "メモ"]
NG_KEYWORDS_TAB_KEY = "ng_keywords"
NG_KEYWORDS_DEFAULT_TTL_SEC = 600

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    def __init__(self, cfg):
        self.cfg = cfg
        creds = self._load_credentials()
        self.service = build("sheets", "v4", credentials=creds)
        self.spreadsheet_id = cfg.spreadsheet_id
        self.tabs = cfg.tabs
        self._ng_cache: dict[str, list[str]] = {}
        self._ng_cache_ts: float = 0.0
        self._ng_cache_ttl: float = float(getattr(cfg, "ng_keywords_cache_ttl_sec", NG_KEYWORDS_DEFAULT_TTL_SEC) or NG_KEYWORDS_DEFAULT_TTL_SEC)
        self._ensure_tabs()

    def _load_credentials(self):
        auth_mode = str(getattr(self.cfg, "auth_mode", "oauth") or "oauth").strip().lower()
        if auth_mode == "service_account":
            return self._load_service_account_credentials()
        return self._load_oauth_credentials()

    def _load_service_account_credentials(self):
        sa_path = Path(getattr(self.cfg, "service_account_json", "./credentials/service_account.json"))
        if not sa_path.exists():
            raise FileNotFoundError(
                f"サービスアカウント JSON がありません: {sa_path}\n"
                "→ Google Cloud Console で発行した service_account.json を配置してください。\n"
                "→ さらに、対象スプレッドシートにそのサービスアカウントのメールアドレスを編集者として共有してください。"
            )
        return ServiceAccountCredentials.from_service_account_file(str(sa_path), scopes=SCOPES)

    def _load_oauth_credentials(self):
        client_path = Path(getattr(self.cfg, "oauth_client_json", "./credentials/oauth_client.json"))
        token_path = Path(getattr(self.cfg, "oauth_token_json", "./credentials/token.json"))
        token_path.parent.mkdir(parents=True, exist_ok=True)

        creds = None
        if token_path.exists():
            creds = OAuthCredentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        if not creds or not creds.valid:
            if not client_path.exists():
                raise FileNotFoundError("credentials/oauth_client.json がありません。import_google_oauth_json.command を実行してください。")
            flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
            creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def _metadata(self):
        return self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()

    def _get_sheet_titles(self) -> set[str]:
        meta = self._metadata()
        return {s["properties"]["title"] for s in meta.get("sheets", [])}

    def _sheet_id_by_title(self):
        meta = self._metadata()
        return {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    def _ensure_tabs(self):
        existing = self._get_sheet_titles()
        requests = []
        for tab in self.tabs.values():
            if tab not in existing:
                requests.append({"addSheet": {"properties": {"title": tab}}})
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()

        for tab in self.tabs.values():
            self._ensure_header(tab)

        self._format_tabs()

    def _ensure_header(self, tab: str):
        ng_tab = self.tabs.get(NG_KEYWORDS_TAB_KEY)
        if ng_tab and tab == ng_tab:
            header_cols = NG_KEYWORDS_HEADERS
            col_end = chr(ord("A") + len(header_cols) - 1)
        else:
            header_cols = HEADERS
            col_end = "M"
        rng = f"{tab}!A1:{col_end}1"
        resp = self.service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=rng,
        ).execute()
        values = resp.get("values", [])
        if not values:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=rng,
                valueInputOption="RAW",
                body={"values": [header_cols]},
            ).execute()

    def _format_tabs(self):
        # 折り返しで行の縦幅が広がる問題を防ぐ
        ids = self._sheet_id_by_title()
        ng_tab = self.tabs.get(NG_KEYWORDS_TAB_KEY)
        requests = []
        for tab in self.tabs.values():
            if ng_tab and tab == ng_tab:
                # NGワードタブは候補ログとはレイアウトが違うのでスキップ
                continue
            sid = ids.get(tab)
            if sid is None:
                continue
            requests.extend([
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sid,
                            "startRowIndex": 0,
                            "endRowIndex": 10000,
                            "startColumnIndex": 0,
                            "endColumnIndex": 13,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "wrapStrategy": "CLIP",
                                "verticalAlignment": "MIDDLE",
                            }
                        },
                        "fields": "userEnteredFormat.wrapStrategy,userEnteredFormat.verticalAlignment",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "ROWS",
                            "startIndex": 1,
                            "endIndex": 10000,
                        },
                        "properties": {"pixelSize": 24},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sid,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 13,
                        },
                        "properties": {"pixelSize": 150},
                        "fields": "pixelSize",
                    }
                },
            ])
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()

    def get_all_unique_ids(self) -> set[str]:
        return set(self.get_unique_id_status_map().keys())

    def get_unique_id_status_map(self) -> dict[str, str]:
        """
        共有シート上の既出IDを、タブ種別ごとに読み込む。
        ローカルDBがない新規PCでも、おすすめ済みはスキップ、除外済みは興味なし対象にできるようにする。
        """
        status_map = {}
        tab_status = {
            "recommended": "recommended",
            "skipped": "skipped",
            "blackband": "blackband",
            "pending": "pending",
        }
        for key, tab in self.tabs.items():
            if str(key) == NG_KEYWORDS_TAB_KEY:
                # NGワードタブは候補ログではないのでスキップ
                continue
            status = tab_status.get(str(key), str(key))
            try:
                resp = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{tab}!C2:C"
                ).execute()
                for row in resp.get("values", []):
                    if row and str(row[0]).strip():
                        uid = str(row[0]).strip().replace("@", "")
                        if uid and uid not in ["ユーザーID", "user_id", "unique_id"]:
                            # おすすめが最優先。除外ログにも同じIDがあっても、おすすめ済みなら再処理しない。
                            if status_map.get(uid) == "recommended":
                                continue
                            status_map[uid] = status
            except Exception:
                pass
        return status_map

    def _normalize_uid_for_dedupe(self, value) -> str:
        return str(value or "").strip().replace("@", "")

    def _fresh_existing_uids_all_tabs(self) -> set[str]:
        """
        別PCの追記も拾うため、記入直前に共有シート全タブのユーザーID列を再取得する。
        C列=ユーザーID前提。
        """
        uids = set()
        for tab in self.tabs.values():
            try:
                resp = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{tab}!C2:C"
                ).execute()
                for row in resp.get("values", []):
                    if row and str(row[0]).strip():
                        uid = self._normalize_uid_for_dedupe(row[0])
                        if uid and uid not in {"ユーザーID", "user_id", "unique_id", "ID", "id"}:
                            uids.add(uid)
            except Exception as e:
                print(f"記入直前の共有既出チェック取得エラー: tab={tab} error={str(e)[:120]}", flush=True)
        return uids

    def _is_duplicate_uid_before_append(self, uid: str) -> bool:
        uid = self._normalize_uid_for_dedupe(uid)
        if not uid:
            return False
        existing = self._fresh_existing_uids_all_tabs()
        return uid in existing

    def append(self, tab_key: str, row: list):
        tab = self.tabs[tab_key]
        row = list(row)

        cleaned = []
        for v in row:
            if v is None:
                cleaned.append("")
            elif isinstance(v, (int, float)):
                cleaned.append(v)
            else:
                s = str(v).replace("\r", " ").replace("\n", " ").replace("\t", " ")
                cleaned.append(" ".join(s.split()))
        row = cleaned

        uid = ""
        try:
            if len(row) > 2:
                uid = self._normalize_uid_for_dedupe(row[2])
        except Exception:
            uid = ""

        if uid and self._is_duplicate_uid_before_append(uid):
            print(f"[PRE_APPEND_DUPLICATE_SKIP] user_id={uid} tab={tab}", flush=True)
            return {"duplicate_skipped": True, "uid": uid, "tab": tab}

        if not row[0]:
            row[0] = "'" + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif not str(row[0]).startswith("'"):
            row[0] = "'" + str(row[0])

        result = self.service.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A:M",
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": [row]},
        ).execute()
        return result

    def get_ng_keywords(self) -> dict[str, list[str]]:
        """
        「NGワード」タブを読み込んで、カテゴリ別の単語リストを返す。
        列構成: A=カテゴリ, B=ワード, C=有効(TRUE/FALSE), D=メモ
        有効列が FALSE/NO/OFF/0/無効 の行はスキップ。
        TTL キャッシュで Sheets API を頻繁に叩かない。失敗時は直前キャッシュを返す(無ければ空 dict)。
        """
        now = time.time()
        if self._ng_cache_ts and (now - self._ng_cache_ts) < self._ng_cache_ttl:
            return self._ng_cache

        tab = self.tabs.get(NG_KEYWORDS_TAB_KEY)
        if not tab:
            self._ng_cache = {}
            self._ng_cache_ts = now
            return self._ng_cache

        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{tab}!A2:D",
            ).execute()
        except Exception as e:
            # 読込失敗時は前回キャッシュにフォールバック。
            # 起動直後でキャッシュが無ければ空 dict を返し、固定リストだけで継続。
            print(f"NGワード読込失敗(キャッシュ流用): {str(e)[:160]}", flush=True)
            return self._ng_cache or {}

        rows = resp.get("values", []) or []
        result: dict[str, list[str]] = {}
        disabled_tokens = {"FALSE", "0", "NO", "OFF", "無効", "false", "off", "no"}
        for row in rows:
            if len(row) < 2:
                continue
            category = str(row[0] or "").strip().lower()
            word = str(row[1] or "").strip()
            if not category or not word:
                continue
            enabled_raw = str(row[2]).strip() if len(row) >= 3 and row[2] is not None else ""
            if enabled_raw and enabled_raw.upper() in disabled_tokens:
                continue
            result.setdefault(category, []).append(word)

        self._ng_cache = result
        self._ng_cache_ts = now
        return result


# === 共有シート重複防止パッチ ===
try:
    import time
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_shared_uid_dedupe_patched", False):
        _orig_append_row_shared_uid_dedupe = gspread.worksheet.Worksheet.append_row
        _shared_uid_cache = {}
        _shared_uid_cache_ttl_sec = 20

        def _normalize_shared_uid(v):
            return str(v or "").strip().replace("@", "")

        def _get_uid_index_from_header(ws):
            try:
                header = ws.row_values(1)
                for name in ["ユーザーID", "user_id", "unique_id", "ID", "id"]:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return 2

        def _load_existing_uids(ws, uid_index):
            key = f"{getattr(ws, 'spreadsheet', '')}:{getattr(ws, 'title', '')}:{uid_index}"
            now = time.time()
            cached = _shared_uid_cache.get(key)
            if cached and now - cached[0] < _shared_uid_cache_ttl_sec:
                return cached[1]
            try:
                values = ws.col_values(uid_index + 1)
                uids = set()
                for v in values[1:]:
                    uid = _normalize_shared_uid(v)
                    if uid and uid not in ["ユーザーID", "user_id", "unique_id"]:
                        uids.add(uid)
                _shared_uid_cache[key] = (now, uids)
                return uids
            except Exception as e:
                print(f"共有既出チェック取得エラー: {str(e)[:120]}", flush=True)
                return set()

        def _shared_uid_dedupe_append_row(self, values, *args, **kwargs):
            try:
                uid_index = _get_uid_index_from_header(self)
                uid = ""
                if isinstance(values, (list, tuple)) and len(values) > uid_index:
                    uid = _normalize_shared_uid(values[uid_index])
                if not uid or uid in ["ユーザーID", "user_id", "unique_id"]:
                    return _orig_append_row_shared_uid_dedupe(self, values, *args, **kwargs)
                existing = _load_existing_uids(self, uid_index)
                if uid in existing:
                    print(f"共有既出スキップ: {uid}", flush=True)
                    return {"shared_duplicate_skipped": True, "uid": uid}
                result = _orig_append_row_shared_uid_dedupe(self, values, *args, **kwargs)
                existing.add(uid)
                return result
            except Exception as e:
                print(f"共有既出チェック失敗のため通常追記します: {str(e)[:120]}", flush=True)
                return _orig_append_row_shared_uid_dedupe(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _shared_uid_dedupe_append_row
        gspread.worksheet.Worksheet._shared_uid_dedupe_patched = True

except Exception as _shared_uid_patch_error:
    print(f"共有シート重複防止パッチ読み込みエラー: {str(_shared_uid_patch_error)[:120]}", flush=True)
# === /共有シート重複防止パッチ ===



# === 記入者名補完パッチ ===
# run.commandで入力した記入者名を、Google Sheets追記直前に反映する。
# 既に記入者/収集者が入っている場合は上書きしない。未設定/空欄のみ補完。
try:
    import os
    from pathlib import Path
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_writer_name_fill_patched", False):
        _orig_append_row_writer_name_fill = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_writer_name_fill = gspread.worksheet.Worksheet.append_rows

        def _get_writer_name_for_sheet():
            name = (
                os.environ.get("TIKTOK_COLLECTOR_NAME")
                or os.environ.get("COLLECTOR_NAME")
                or os.environ.get("SHEET_WRITER_NAME")
                or ""
            ).strip()
            if name:
                return name

            try:
                for p in [
                    Path.cwd() / ".collector_name",
                    Path(__file__).resolve().parents[2] / ".collector_name",
                ]:
                    if p.exists():
                        raw = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                        if raw and raw[0].strip():
                            return raw[0].strip()
            except Exception:
                pass
            return ""

        def _writer_col_index(ws):
            try:
                header = ws.row_values(1)
                for name in ["記入者", "収集者", "担当者", "入力者", "collector", "writer", "name"]:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return 1

        def _should_fill_writer(v):
            s = str(v or "").strip()
            return s == "" or s in ["未設定", "未入力", "None", "none", "null", "-", "ー"]

        def _fill_writer_name(ws, row):
            try:
                if not isinstance(row, (list, tuple)):
                    return row
                writer = _get_writer_name_for_sheet()
                if not writer:
                    return row

                row = list(row)
                idx = _writer_col_index(ws)
                while len(row) <= idx:
                    row.append("")

                if _should_fill_writer(row[idx]):
                    row[idx] = writer
                return row
            except Exception as e:
                print(f"記入者名補完エラー: {str(e)[:120]}", flush=True)
                return row

        def _append_row_with_writer_name(self, values, *args, **kwargs):
            values = _fill_writer_name(self, values)
            return _orig_append_row_writer_name_fill(self, values, *args, **kwargs)

        def _append_rows_with_writer_name(self, values, *args, **kwargs):
            try:
                if isinstance(values, (list, tuple)):
                    values = [_fill_writer_name(self, row) for row in values]
            except Exception as e:
                print(f"記入者名一括補完エラー: {str(e)[:120]}", flush=True)
            return _orig_append_rows_writer_name_fill(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_with_writer_name
        gspread.worksheet.Worksheet.append_rows = _append_rows_with_writer_name
        gspread.worksheet.Worksheet._writer_name_fill_patched = True

except Exception as _writer_name_fill_error:
    print(f"記入者名補完パッチ読み込みエラー: {str(_writer_name_fill_error)[:120]}", flush=True)
# === /記入者名補完パッチ ===


# === 色付き漏れ行対策: シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_colored_leak_final_guard_patched", False):
        _orig_append_row_colored_leak_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_colored_leak_guard = gspread.worksheet.Worksheet.append_rows

        _COLORED_LEAK_NG_WORDS = ['Doublefedora', 'mafioso', 'forsaken', 'ベトナムフェスティバル', 'ウエノデコリアンフェスタ', 'コリアンフェスタ', 'カリブラテンアメリカストリート', 'ラテンアメリカ', '日比谷音楽祭', 'アウトドアシネマ', 'スタンダップコメディ', 'standupcomedy', 'crowdwork', 'ほんまやでダンス', 'newmusic', 'いいねください', 'fypツ', 'smail', 'facebook.com', 'mibextid', '可愛い女の子', '毎日 可愛い女の子', '宝鐘マリン', 'くださいませチャレンジ', '愛くださいませ', '成熟した女性', '成熟', 'cosplay', 'cosplayer', 'neongenesisevangelion', 'アスカ', 'lingerie', 'gorgeous', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow', 'ConfidenceIsKey', 'PR エバーカラー', 'エバーカラー', 'カラコン', 'ROWfreelove', 'rowlove', 'rowbuzz', 'charlesandsylvia', 'wolfieandsylvia', 'couplescomedy', 'じゅんな', 'ゆうな']

        def _colored_leak_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _colored_leak_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _colored_leak_reason(ws, row):
            try:
                uid_idx = _colored_leak_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _colored_leak_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _colored_leak_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _colored_leak_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _colored_leak_cell(row, uid_idx)
                name = _colored_leak_cell(row, name_idx)
                tags = _colored_leak_cell(row, tag_idx)
                bio = _colored_leak_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return ""

                text = " ".join([uid, name, tags, bio])
                low = text.lower()
                tags_lower = tags.lower()

                for w in _COLORED_LEAK_NG_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return f"NGワード({ws_})"

                if bio == "" and tags:
                    has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", tags) is not None
                    has_ascii_letter = re.search(r"[a-zA-Z]", tags) is not None
                    if has_ascii_letter and not has_japanese:
                        return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

                if bio == "" and "fyp" in tags_lower:
                    return "プロフィール紹介文空欄(fyp)"

                if bio == "" and tags.strip() in ["可愛", "可愛い"]:
                    return "ハッシュタグ単体NG(可愛)"

                if "可愛い" in tags and "女の子" in tags:
                    return "ハッシュタグNG(可愛い女の子)"

                return ""
            except Exception as e:
                print(f"色付き漏れ最終ガード判定エラー: {str(e)[:120]}", flush=True)
                return ""

        def _append_row_colored_leak_guard(self, values, *args, **kwargs):
            reason = _colored_leak_reason(self, values)
            if reason:
                uid_idx = _colored_leak_header_idx(self, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                uid = _colored_leak_cell(values, uid_idx)
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"colored_leak_final_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_colored_leak_guard(self, values, *args, **kwargs)

        def _append_rows_colored_leak_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_colored_leak_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    reason = _colored_leak_reason(self, row)
                    if reason:
                        uid_idx = _colored_leak_header_idx(self, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                        uid = _colored_leak_cell(row, uid_idx)
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"colored_leak_final_guard_skipped_rows": skipped}
                return _orig_append_rows_colored_leak_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"色付き漏れ最終ガード失敗のため通常追記します: {str(e)[:120]}", flush=True)
                return _orig_append_rows_colored_leak_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_colored_leak_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_colored_leak_guard
        gspread.worksheet.Worksheet._colored_leak_final_guard_patched = True

except Exception as _colored_leak_final_guard_error:
    print(f"色付き漏れ行対策ガード読み込みエラー: {str(_colored_leak_final_guard_error)[:120]}", flush=True)
# === /色付き漏れ行対策: シート書き込み直前ガード ===


# === 色付き漏れ行対策v2: シート書き込み直前ガード ※litlink除外しない ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_colored_leak_final_guard_v2_patched", False):
        _orig_append_row_colored_leak_guard_v2 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_colored_leak_guard_v2 = gspread.worksheet.Worksheet.append_rows

        _COLORED_LEAK_NG_WORDS_V2 = ['Doublefedora', 'mafioso', 'forsaken', 'ベトナムフェスティバル', 'ウエノデコリアンフェスタ', 'コリアンフェスタ', 'カリブラテンアメリカストリート', 'ラテンアメリカ', '日比谷音楽祭', 'アウトドアシネマ', 'スタンダップコメディ', 'standupcomedy', 'crowdwork', 'ほんまやでダンス', 'newmusic', 'いいねください', 'fypツ', 'smail', 'facebook.com', 'mibextid', '可愛い女の子', '毎日 可愛い女の子', '宝鐘マリン', 'くださいませチャレンジ', '愛くださいませ', '成熟した女性', '成熟', 'cosplay', 'cosplayer', 'neongenesisevangelion', 'アスカ', 'lingerie', 'gorgeous', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow', 'ConfidenceIsKey', 'PR エバーカラー', 'エバーカラー', 'カラコン', 'ROWfreelove', 'rowlove', 'rowbuzz', 'charlesandsylvia', 'wolfieandsylvia', 'couplescomedy', 'じゅんな', 'ゆうな']

        def _colored_leak_cell_v2(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _colored_leak_header_idx_v2(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _colored_leak_reason_v2(ws, row):
            try:
                uid_idx = _colored_leak_header_idx_v2(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _colored_leak_header_idx_v2(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _colored_leak_header_idx_v2(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _colored_leak_header_idx_v2(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _colored_leak_cell_v2(row, uid_idx)
                name = _colored_leak_cell_v2(row, name_idx)
                tags = _colored_leak_cell_v2(row, tag_idx)
                bio = _colored_leak_cell_v2(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return ""

                text = " ".join([uid, name, tags, bio])
                low = text.lower()
                tags_lower = tags.lower()
                has_litlink = ("lit.link" in low) or ("litlink" in low)

                for w in _COLORED_LEAK_NG_WORDS_V2:
                    ws_ = str(w or "").strip()
                    if not ws_:
                        continue
                    if ws_.lower() in ["litlink", "lit.link"]:
                        continue
                    if ws_.lower() in low:
                        return f"NGワード({ws_})"

                for link_ng in ["facebook.com", "mibextid", "onlyfans", "ofans", "fansly"]:
                    if link_ng in low and not has_litlink:
                        return f"外部リンクNG({link_ng})"

                if bio == "" and tags:
                    has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", tags) is not None
                    has_ascii_letter = re.search(r"[a-zA-Z]", tags) is not None
                    if has_ascii_letter and not has_japanese:
                        return "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

                if bio == "" and "fyp" in tags_lower:
                    return "プロフィール紹介文空欄(fyp)"

                if bio == "" and tags.strip() in ["可愛", "可愛い"]:
                    return "ハッシュタグ単体NG(可愛)"

                if "可愛い" in tags and "女の子" in tags:
                    return "ハッシュタグNG(可愛い女の子)"

                return ""
            except Exception as e:
                print(f"色付き漏れv2最終ガード判定エラー: {str(e)[:120]}", flush=True)
                return ""

        def _append_row_colored_leak_guard_v2(self, values, *args, **kwargs):
            reason = _colored_leak_reason_v2(self, values)
            if reason:
                uid_idx = _colored_leak_header_idx_v2(self, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                uid = _colored_leak_cell_v2(values, uid_idx)
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"colored_leak_final_guard_v2_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_colored_leak_guard_v2(self, values, *args, **kwargs)

        def _append_rows_colored_leak_guard_v2(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_colored_leak_guard_v2(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    reason = _colored_leak_reason_v2(self, row)
                    if reason:
                        uid_idx = _colored_leak_header_idx_v2(self, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                        uid = _colored_leak_cell_v2(row, uid_idx)
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"colored_leak_final_guard_v2_skipped_rows": skipped}
                return _orig_append_rows_colored_leak_guard_v2(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"色付き漏れv2最終ガード失敗のため通常追記します: {str(e)[:120]}", flush=True)
                return _orig_append_rows_colored_leak_guard_v2(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_colored_leak_guard_v2
        gspread.worksheet.Worksheet.append_rows = _append_rows_colored_leak_guard_v2
        gspread.worksheet.Worksheet._colored_leak_final_guard_v2_patched = True

except Exception as _colored_leak_final_guard_v2_error:
    print(f"色付き漏れ行対策v2ガード読み込みエラー: {str(_colored_leak_final_guard_v2_error)[:120]}", flush=True)
# === /色付き漏れ行対策v2: シート書き込み直前ガード ===


# === 1539行目以降の色付きアカウントID除外: シート書き込み直前ガード ===
try:
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_colored_id_exclusion_1539_patched", False):
        _orig_append_row_colored_id_1539 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_colored_id_1539 = gspread.worksheet.Worksheet.append_rows
        _COLORED_EXCLUDED_IDS_1539 = set(['erishinn', 'layna0930', 'olehistrinya43', 'kata_kata_hati_yo', 'nasyacuw3k', 'una____1116', 'uutkyds2189166932', '5dfgegd', 'zella_matcha'])

        def _colored_id_1539_norm(v):
            return str(v or "").strip().replace("@", "")

        def _colored_id_1539_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _colored_id_1539_reason(ws, row):
            try:
                uid_idx = _colored_id_1539_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                if not isinstance(row, (list, tuple)) or len(row) <= uid_idx:
                    return "", ""
                uid = _colored_id_1539_norm(row[uid_idx])
                if uid and uid in _COLORED_EXCLUDED_IDS_1539:
                    return uid, f"色付き除外ID({uid})"
                return uid, ""
            except Exception as e:
                print(f"色付き除外ID判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_colored_id_1539(self, values, *args, **kwargs):
            uid, reason = _colored_id_1539_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"colored_id_exclusion_1539_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_colored_id_1539(self, values, *args, **kwargs)

        def _append_rows_colored_id_1539(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_colored_id_1539(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _colored_id_1539_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"colored_id_exclusion_1539_skipped_rows": skipped}
                return _orig_append_rows_colored_id_1539(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"色付き除外ID一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_colored_id_1539(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_colored_id_1539
        gspread.worksheet.Worksheet.append_rows = _append_rows_colored_id_1539
        gspread.worksheet.Worksheet._colored_id_exclusion_1539_patched = True

except Exception as _colored_id_1539_error:
    print(f"1539行目以降の色付きアカウントID除外パッチ読み込みエラー: {str(_colored_id_1539_error)[:120]}", flush=True)
# === /1539行目以降の色付きアカウントID除外 ===


# === 類似アカウント除外v1: シート書き込み直前ガード 1〜5 ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_similar_account_guard_1to5_patched", False):
        _orig_append_row_similar_guard_1to5 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_similar_guard_1to5 = gspread.worksheet.Worksheet.append_rows

        _SIM_ADULT_WORDS_1TO5 = ['lingerie', 'gorgeous', 'mature', 'maturewoman', 'maturewomen', '成熟', '成熟した女性', '色気', 'セクシー', 'sexy', '大人', '大人女子', '大人ガーリー', 'big.ass', 'ass9855', 'MagneticBeauty', 'SelfLoveVibes', 'GlamAndGrow', 'ConfidenceIsKey', 'beauty', 'glam']
        _SIM_COSPLAY_WORDS_1TO5 = ['cosplay', 'cosplayer', 'コスプレ', 'レイヤー', '宝鐘マリン', 'ホロライブ', 'hololive', 'アスカ', 'asuka', 'neongenesisevangelion', 'evangelion', 'エヴァ', 'エヴァンゲリオン', 'fivem', 'gta', 'gtarp', 'ゲーム実況', 'gaming']
        _SIM_EXTERNAL_WORDS_1TO5 = ['facebook.com', 'mibextid', 'onlyfans', 'ofans', 'fansly']

        def _sim_cell_1to5(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _sim_header_idx_1to5(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _sim_reason_1to5(ws, row):
            try:
                uid_idx = _sim_header_idx_1to5(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _sim_header_idx_1to5(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _sim_header_idx_1to5(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _sim_header_idx_1to5(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _sim_cell_1to5(row, uid_idx).replace("@", "")
                name = _sim_cell_1to5(row, name_idx)
                tags = _sim_cell_1to5(row, tag_idx)
                bio = _sim_cell_1to5(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()
                has_litlink = ("lit.link" in low) or ("litlink" in low)

                # 3. 外部リンク誘導系。ただしlitlink除外しない
                for link_ng in _SIM_EXTERNAL_WORDS_1TO5:
                    if link_ng in low and not has_litlink:
                        return uid, f"外部リンクNG({link_ng})"

                # 4. 美容・色気・成人・下着・成熟系
                for adult_w in _SIM_ADULT_WORDS_1TO5:
                    adult_s = str(adult_w or "").strip()
                    if not adult_s:
                        continue
                    if adult_s.lower() == "beauty":
                        if "beauty" in low and (bio == "" or re.search(r"[a-zA-Z]", tags)):
                            return uid, "NGワード(beauty系)"
                        continue
                    if adult_s.lower() in low:
                        return uid, f"NGワード({adult_s})"

                # 5. コスプレ・アニメ・キャラ・ゲーム系
                for cg_w in _SIM_COSPLAY_WORDS_1TO5:
                    cg_s = str(cg_w or "").strip()
                    if cg_s and cg_s.lower() in low:
                        return uid, f"NGワード({cg_s})"

                # 1. プロフ空欄 + 英字ハッシュタグのみ
                if bio == "" and tags:
                    has_japanese_tag = re.search(r"[ぁ-んァ-ヶ一-龥]", tags) is not None
                    has_ascii_tag = re.search(r"[a-zA-Z]", tags) is not None
                    if has_ascii_tag and not has_japanese_tag:
                        return uid, "外国語/海外(英字タグのみ/プロフィール紹介文空欄)"

                # 2. プロフ空欄 + ランダムIDっぽいユーザーID
                uid_clean = re.sub(r"[^a-zA-Z0-9]", "", uid).lower()
                uid_has_letter = re.search(r"[a-z]", uid_clean) is not None
                uid_has_digit = re.search(r"[0-9]", uid_clean) is not None
                uid_has_sep = ("_" in uid) or ("." in uid) or ("-" in uid)
                if bio == "" and len(uid_clean) >= 6 and uid_has_letter and uid_has_digit and not uid_has_sep:
                    return uid, "ランダムID/プロフィール紹介文空欄"

                return uid, ""
            except Exception as e:
                print(f"類似アカウント除外v1判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_similar_guard_1to5(self, values, *args, **kwargs):
            uid, reason = _sim_reason_1to5(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"similar_account_guard_1to5_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_similar_guard_1to5(self, values, *args, **kwargs)

        def _append_rows_similar_guard_1to5(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_similar_guard_1to5(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _sim_reason_1to5(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"similar_account_guard_1to5_skipped_rows": skipped}
                return _orig_append_rows_similar_guard_1to5(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"類似アカウント除外v1一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_similar_guard_1to5(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_similar_guard_1to5
        gspread.worksheet.Worksheet.append_rows = _append_rows_similar_guard_1to5
        gspread.worksheet.Worksheet._similar_account_guard_1to5_patched = True

except Exception as _similar_guard_1to5_error:
    print(f"類似アカウント除外v1ガード読み込みエラー: {str(_similar_guard_1to5_error)[:120]}", flush=True)
# === /類似アカウント除外v1: シート書き込み直前ガード ===



# === 記入者名 最終補完パッチ v2 ===
# Google Sheets追記直前にも、記入者/収集者列が空欄/未設定なら補完する。
try:
    import os
    from pathlib import Path
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_writer_name_final_fill_v2_patched", False):
        _orig_append_row_writer_name_final_v2 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_writer_name_final_v2 = gspread.worksheet.Worksheet.append_rows

        def _writer_final_v2_name():
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
                for p in [
                    Path.cwd() / ".collector_name",
                    Path(__file__).resolve().parents[2] / ".collector_name",
                    Path(__file__).resolve().parents[3] / ".collector_name",
                ]:
                    if p.exists():
                        lines = p.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                        if lines and lines[0].strip():
                            return lines[0].strip()
            except Exception:
                pass
            return ""

        def _writer_final_v2_col(ws):
            try:
                header = ws.row_values(1)
                for name in ["記入者", "収集者", "担当者", "入力者", "collector", "writer", "name"]:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return 1

        def _writer_final_v2_need(v):
            s = str(v or "").strip()
            return s == "" or s in ["未設定", "未入力", "None", "none", "null", "-", "ー"]

        def _writer_final_v2_fill(ws, row):
            try:
                if not isinstance(row, (list, tuple)):
                    return row
                writer = _writer_final_v2_name()
                if not writer:
                    return row
                row = list(row)
                idx = _writer_final_v2_col(ws)
                while len(row) <= idx:
                    row.append("")
                if _writer_final_v2_need(row[idx]):
                    row[idx] = writer
                return row
            except Exception as e:
                print(f"記入者名最終補完v2エラー: {str(e)[:120]}", flush=True)
                return row

        def _append_row_writer_final_v2(self, values, *args, **kwargs):
            values = _writer_final_v2_fill(self, values)
            return _orig_append_row_writer_name_final_v2(self, values, *args, **kwargs)

        def _append_rows_writer_final_v2(self, values, *args, **kwargs):
            try:
                if isinstance(values, (list, tuple)):
                    values = [_writer_final_v2_fill(self, row) for row in values]
            except Exception as e:
                print(f"記入者名一括最終補完v2エラー: {str(e)[:120]}", flush=True)
            return _orig_append_rows_writer_name_final_v2(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_writer_final_v2
        gspread.worksheet.Worksheet.append_rows = _append_rows_writer_final_v2
        gspread.worksheet.Worksheet._writer_name_final_fill_v2_patched = True

except Exception as _writer_name_final_fill_v2_error:
    print(f"記入者名 最終補完パッチv2読み込みエラー: {str(_writer_name_final_fill_v2_error)[:120]}", flush=True)
# === /記入者名 最終補完パッチ v2 ===


# === 追加除外: シート書き込み直前ガード 外国文字/着替えフェチ/shit/絵文字のみBio ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_foreign_fetish_shit_guard_patched", False):
        _orig_append_row_foreign_fetish_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_foreign_fetish_guard = gspread.worksheet.Worksheet.append_rows

        _FOREIGN_FETISH_EXTRA_WORDS = ['shit', 'お着替え', '着替え', '着替えチャレンジ', 'フェチ', 'fetish', 'ミニサイズ', 'パレオ']

        def _ff_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _ff_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _ff_reason(ws, row):
            try:
                uid_idx = _ff_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _ff_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _ff_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _ff_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _ff_cell(row, uid_idx).replace("@", "")
                name = _ff_cell(row, name_idx)
                tags = _ff_cell(row, tag_idx)
                bio = _ff_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()

                for w in _FOREIGN_FETISH_EXTRA_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"NGワード({ws_})"

                if any(
                    (0x1000 <= ord(ch) <= 0x109F)
                    or (0x1780 <= ord(ch) <= 0x17FF)
                    or (0x0E80 <= ord(ch) <= 0x0EFF)
                    for ch in full
                ):
                    return uid, "外国語/海外(東南アジア系文字)"

                if bio:
                    bio_has_meaning_text = re.search(r"[a-zA-Z0-9ぁ-んァ-ヶ一-龥]", bio) is not None
                    bio_is_emoji_only = not bio_has_meaning_text
                    tags_has_ascii = re.search(r"[a-zA-Z]", tags) is not None
                    tags_has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", tags) is not None
                    if bio_is_emoji_only and tags_has_ascii and not tags_has_japanese:
                        return uid, "プロフィール紹介文が絵文字のみ/英字タグ"

                return uid, ""
            except Exception as e:
                print(f"追加除外判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_foreign_fetish_guard(self, values, *args, **kwargs):
            uid, reason = _ff_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"foreign_fetish_shit_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_foreign_fetish_guard(self, values, *args, **kwargs)

        def _append_rows_foreign_fetish_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_foreign_fetish_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _ff_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"foreign_fetish_shit_guard_skipped_rows": skipped}
                return _orig_append_rows_foreign_fetish_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"追加除外一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_foreign_fetish_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_foreign_fetish_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_foreign_fetish_guard
        gspread.worksheet.Worksheet._foreign_fetish_shit_guard_patched = True

except Exception as _foreign_fetish_shit_guard_error:
    print(f"追加除外ガード読み込みエラー: {str(_foreign_fetish_shit_guard_error)[:120]}", flush=True)
# === /追加除外: シート書き込み直前ガード 外国文字/着替えフェチ/shit/絵文字のみBio ===


# === 追加除外: シート書き込み直前ガード ハッシュタグ08/09 + 配信系 ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_tag_08_09_stream_guard_patched", False):
        _orig_append_row_tag_08_09_stream_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_tag_08_09_stream_guard = gspread.worksheet.Worksheet.append_rows

        _STREAM_WORDS_08_09 = ['配信', 'ｻﾌﾞ配信', 'サブ配信', '配信専用', 'テキーラ配信', '本垢', '本アカ', '本アカウント', '他にもあります']

        def _s08_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _s08_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _s08_reason(ws, row):
            try:
                uid_idx = _s08_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _s08_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _s08_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _s08_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _s08_cell(row, uid_idx).replace("@", "")
                name = _s08_cell(row, name_idx)
                tags = _s08_cell(row, tag_idx)
                bio = _s08_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()

                for sw in _STREAM_WORDS_08_09:
                    sws = str(sw or "").strip()
                    if sws and sws.lower() in low:
                        return uid, f"NGワード({sws})"

                tags_norm_digits = tags.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                tag_tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+", tags_norm_digits) if t]
                if "08" in tag_tokens:
                    return uid, "ハッシュタグNG(08)"
                if "09" in tag_tokens:
                    return uid, "ハッシュタグNG(09)"

                return uid, ""
            except Exception as e:
                print(f"08/09/配信系判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_tag_08_09_stream_guard(self, values, *args, **kwargs):
            uid, reason = _s08_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"tag_08_09_stream_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_tag_08_09_stream_guard(self, values, *args, **kwargs)

        def _append_rows_tag_08_09_stream_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_tag_08_09_stream_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _s08_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"tag_08_09_stream_guard_skipped_rows": skipped}
                return _orig_append_rows_tag_08_09_stream_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"08/09/配信系一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_tag_08_09_stream_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_tag_08_09_stream_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_tag_08_09_stream_guard
        gspread.worksheet.Worksheet._tag_08_09_stream_guard_patched = True

except Exception as _tag_08_09_stream_guard_error:
    print(f"08/09/配信系ガード読み込みエラー: {str(_tag_08_09_stream_guard_error)[:120]}", flush=True)
# === /追加除外: シート書き込み直前ガード ハッシュタグ08/09 + 配信系 ===


# === 追加除外: シート書き込み直前ガード インドネシア語/マレー語系 ===
try:
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_indonesian_malay_guard_patched", False):
        _orig_append_row_indo_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_indo_guard = gspread.worksheet.Worksheet.append_rows

        _INDO_MALAY_WORDS = ['cewek', 'cewekcantik', 'cewekidaman', 'wanita', 'masih mencari', 'cantik', 'idaman', 'mencari', 'gadis', 'perempuan', 'indonesia', 'jakarta', 'malaysia', 'malay']

        def _indo_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _indo_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _indo_reason(ws, row):
            try:
                uid_idx = _indo_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _indo_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _indo_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _indo_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _indo_cell(row, uid_idx).replace("@", "")
                name = _indo_cell(row, name_idx)
                tags = _indo_cell(row, tag_idx)
                bio = _indo_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio]).lower()

                for w in _INDO_MALAY_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in full:
                        return uid, f"外国語/海外({ws_})"

                return uid, ""
            except Exception as e:
                print(f"インドネシア語/マレー語系判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_indo_guard(self, values, *args, **kwargs):
            uid, reason = _indo_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"indonesian_malay_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_indo_guard(self, values, *args, **kwargs)

        def _append_rows_indo_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_indo_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _indo_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"indonesian_malay_guard_skipped_rows": skipped}
                return _orig_append_rows_indo_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"インドネシア語/マレー語系一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_indo_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_indo_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_indo_guard
        gspread.worksheet.Worksheet._indonesian_malay_guard_patched = True

except Exception as _indonesian_malay_guard_error:
    print(f"インドネシア語/マレー語系ガード読み込みエラー: {str(_indonesian_malay_guard_error)[:120]}", flush=True)
# === /追加除外: シート書き込み直前ガード インドネシア語/マレー語系 ===


# === 追加除外: シート書き込み直前ガード ベトナム系/インスタ誘導/短文メンション ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_vn_insta_mention_guard_patched", False):
        _orig_append_row_vn_insta_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_vn_insta_guard = gspread.worksheet.Worksheet.append_rows

        _VN_ROMAN_TAG_WORDS = ['vaycongchua', 'phongcachphap', 'bachnguyetquang', 'stylenangtho', 'nangtho', 'outfitlangman', 'langman', 'vay', 'congchua', 'phongcach', 'bong_iu', 'bongiu', 'hihi']
        _PROMO_WORDS = ['affiliatemarketing', 'affiliate marketing', 'いんすたきて', 'インスタきて', 'インスタ来て', 'instaきて', 'instagramきて', 'いんすた来て', 'ID→', 'id→', 'ID:', 'id:']
        _KPOP_SHORT_NOISE_WORDS = ['cortis']

        def _vn_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _vn_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _vn_reason(ws, row):
            try:
                uid_idx = _vn_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _vn_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _vn_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _vn_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _vn_cell(row, uid_idx).replace("@", "")
                name = _vn_cell(row, name_idx)
                tags = _vn_cell(row, tag_idx)
                bio = _vn_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()
                tags_low = tags.lower()
                bio_low = bio.lower()

                for w in _VN_ROMAN_TAG_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"外国語/海外({ws_})"

                for w in _PROMO_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"SNS誘導({ws_})"

                if "affiliate" in low:
                    return uid, "NGワード(affiliate)"

                if "fyp" in tags_low and re.search(r"(いんすた|インスタ|insta|instagram|id\s*[→:：])", bio_low):
                    return uid, "SNS誘導(fyp+インスタID)"

                mention_only = re.fullmatch(r"@?[a-zA-Z0-9_.]{1,20}", bio or "") is not None
                if mention_only and len(bio.replace("@", "").strip()) <= 4:
                    return uid, "プロフィール紹介文が短すぎるメンションのみ"

                for w in _KPOP_SHORT_NOISE_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in tags_low and len(bio) <= 5:
                        return uid, f"海外/ノイズタグ({ws_})"

                return uid, ""
            except Exception as e:
                print(f"ベトナム系/インスタ誘導/短文メンション判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_vn_insta_guard(self, values, *args, **kwargs):
            uid, reason = _vn_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"vn_insta_mention_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_vn_insta_guard(self, values, *args, **kwargs)

        def _append_rows_vn_insta_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_vn_insta_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _vn_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"vn_insta_mention_guard_skipped_rows": skipped}
                return _orig_append_rows_vn_insta_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"ベトナム系/インスタ誘導/短文メンション一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_vn_insta_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_vn_insta_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_vn_insta_guard
        gspread.worksheet.Worksheet._vn_insta_mention_guard_patched = True

except Exception as _vn_insta_mention_guard_error:
    print(f"ベトナム系/インスタ誘導/短文メンションガード読み込みエラー: {str(_vn_insta_mention_guard_error)[:120]}", flush=True)
# === /追加除外: シート書き込み直前ガード ベトナム系/インスタ誘導/短文メンション ===


# === 追加除外: シート書き込み直前ガード 量産タグ/アイドル系/海外音楽系 ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_noise_idol_music_guard_patched", False):
        _orig_append_row_noise_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_noise_guard = gspread.worksheet.Worksheet.append_rows
        _NOISE_IDOL_MUSIC_WORDS = ['daun muda', 'daun', 'muda', '田島櫻子', '田島櫻子ちゃん', 'onephony', 'slipknot', 'metal', "don't like small talk", 'dont like small talk', 'small talk']

        def _noise_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _noise_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _noise_reason(ws, row):
            try:
                uid_idx = _noise_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _noise_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _noise_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _noise_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _noise_cell(row, uid_idx).replace("@", "")
                name = _noise_cell(row, name_idx)
                tags = _noise_cell(row, tag_idx)
                bio = _noise_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()
                tags_low = tags.lower()
                bio_s = str(bio or "").strip()

                for w in _NOISE_IDOL_MUSIC_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"NGワード({ws_})"

                if re.search(r"(?i)(?<![a-z])([a-z])\1{7,}(?![a-z])", tags):
                    return uid, "ハッシュタグNG(同一英字連続)"

                if "fyp" in tags_low and re.search(r"(?i)([a-z])\1{5,}", tags):
                    return uid, "ハッシュタグNG(fyp+同一英字連続)"

                has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", full) is not None
                if not has_japanese and re.search(r"[a-zA-Z]", tags) and re.search(r"[a-zA-Z]", bio_s):
                    if len(bio_s) <= 30:
                        return uid, "外国語/海外(英字タグ+短文英字Bio)"

                if bio_s == "" and ("onephony" in tags_low or "田島櫻子" in tags):
                    return uid, "アイドル/ファン系タグ(プロフィール紹介文空欄)"

                return uid, ""
            except Exception as e:
                print(f"量産タグ/アイドル系/海外音楽系判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_noise_guard(self, values, *args, **kwargs):
            uid, reason = _noise_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"noise_idol_music_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_noise_guard(self, values, *args, **kwargs)

        def _append_rows_noise_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_noise_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _noise_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"noise_idol_music_guard_skipped_rows": skipped}
                return _orig_append_rows_noise_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"量産タグ/アイドル系/海外音楽系一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_noise_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_noise_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_noise_guard
        gspread.worksheet.Worksheet._noise_idol_music_guard_patched = True

except Exception as _noise_guard_error:
    print(f"量産タグ/アイドル系/海外音楽系ガード読み込みエラー: {str(_noise_guard_error)[:120]}", flush=True)
# === /追加除外: シート書き込み直前ガード 量産タグ/アイドル系/海外音楽系 ===


# === 追加除外: シート書き込み直前ガード 日本以外の海外アカウント除外強化 ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_strict_non_japan_guard_patched", False):
        _orig_append_row_strict_nj_guard = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_strict_nj_guard = gspread.worksheet.Worksheet.append_rows

        _NJ_CN_PHRASES = ['今天', '也是', '被热', '热可可', '旧电影', '电影', '治愈', '的一天', '关注', '私信', '主页', '置顶', '找我', '美女', '漂亮', '可爱', '点赞', '评论', '转发', '粉丝', '视频', '熱門', '热门', '推荐', '大家好', '我是', '谢谢', '喜欢', '生活', '日常', '女孩', '女生']
        _NJ_CN_CHARS = ['这', '们', '为', '热', '电', '说', '话', '买', '卖', '体', '会', '觉', '让', '从', '给', '发', '欢', '乐', '国', '学', '广', '东', '网', '写', '气', '应', '旧', '后', '边', '过', '还', '进', '长', '门']
        _NJ_STRICT_WORDS = ['feilvbin', '絡み募', 'xuhuong', 'xuhuongtiktok', 'gaixinh', 'gaixinhtiktok', 'xinhdep', 'cewek', 'wanita', 'masih mencari', 'cantik', 'mencari', 'dungmai', 'halinh', 'babygirl', 'bikini', 'follow tui', 'mọi người']
        _NJ_EN_WORDS = ['i', 'you', 'we', 'they', 'he', 'she', 'my', 'your', 'the', 'and', 'to', 'with', 'for', 'from', 'like', 'love', 'dont', "don't", 'cant', "can't", 'can', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'me', 'at', 'in', 'on', 'of', 'small', 'talk']

        def _nj_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _nj_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _nj_en_sentence_like(s):
            low = str(s or "").lower()
            words = re.findall(r"[a-zA-Z']{2,}", low)
            if len(words) >= 6:
                return True
            hits = 0
            for ew in _NJ_EN_WORDS:
                if re.search(r"\b" + re.escape(str(ew).lower()) + r"\b", low):
                    hits += 1
            if len(words) >= 3 and hits >= 2:
                return True
            if len(words) >= 3 and re.search(r"[.!?]", str(s or "")):
                return True
            return False

        def _nj_reason(ws, row):
            try:
                uid_idx = _nj_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _nj_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _nj_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _nj_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _nj_cell(row, uid_idx).replace("@", "")
                name = _nj_cell(row, name_idx)
                tags = _nj_cell(row, tag_idx)
                bio = _nj_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()

                for w in _NJ_STRICT_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"外国語/海外({ws_})"

                for p in _NJ_CN_PHRASES:
                    if p and p in full:
                        return uid, f"外国語/海外(中国語:{p})"

                cn_hit = 0
                for ch in _NJ_CN_CHARS:
                    if ch and ch in full:
                        cn_hit += 1
                if cn_hit >= 2:
                    return uid, "外国語/海外(中国語/簡体字)"
                if bio and cn_hit >= 1 and not re.search(r"[ぁ-んァ-ヶ]", bio):
                    return uid, "外国語/海外(中国語/簡体字Bio)"

                if re.search(r"[\u1000-\u109F\u1780-\u17FF\u0E80-\u0EFF\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0900-\u097F]", full):
                    return uid, "外国語/海外(非日本語文字種)"

                if re.search(r"[ăâêôơưđàáạảãằắặẳẵầấậẩẫèéẹẻẽềếệểễìíịỉĩòóọỏõồốộổỗờớợởỡùúụủũừứựửữỳýỵỷỹ]", low):
                    return uid, "外国語/海外(ベトナム語文字)"

                if _nj_en_sentence_like(bio):
                    return uid, "外国語/海外(英語文章Bio)"
                if not re.search(r"[ぁ-んァ-ヶ一-龥]", full) and _nj_en_sentence_like(full):
                    return uid, "外国語/海外(英語文章)"

                hangul_count = len(re.findall(r"[\uAC00-\uD7AF]", full))
                hangul_tokens = re.findall(r"[\uAC00-\uD7AF]{2,}", full)
                if hangul_count >= 10 or len(hangul_tokens) >= 3:
                    return uid, "外国語/海外(韓国語文章)"
                if bio and len(re.findall(r"[\uAC00-\uD7AF]", bio)) >= 6:
                    return uid, "外国語/海外(韓国語Bio)"

                return uid, ""
            except Exception as e:
                print(f"海外除外強化判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_strict_nj_guard(self, values, *args, **kwargs):
            uid, reason = _nj_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"strict_non_japan_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_strict_nj_guard(self, values, *args, **kwargs)

        def _append_rows_strict_nj_guard(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_strict_nj_guard(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _nj_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"strict_non_japan_guard_skipped_rows": skipped}
                return _orig_append_rows_strict_nj_guard(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"海外除外強化一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_strict_nj_guard(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_strict_nj_guard
        gspread.worksheet.Worksheet.append_rows = _append_rows_strict_nj_guard
        gspread.worksheet.Worksheet._strict_non_japan_guard_patched = True

except Exception as _strict_non_japan_guard_error:
    print(f"海外除外強化ガード読み込みエラー: {str(_strict_non_japan_guard_error)[:120]}", flush=True)
# === /追加除外: シート書き込み直前ガード 日本以外の海外アカウント除外強化 ===



# === 共有シート重複防止 強化パッチ v2 ===
# 複数メンバーが同じ共有シートに書く場合でも、追記直前に既存ユーザーID/プロフURLを確認して重複記入を防ぐ。
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_shared_sheet_duplicate_guard_v2_patched", False):
        _orig_append_row_shared_dup_v2 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_shared_dup_v2 = gspread.worksheet.Worksheet.append_rows

        def _shared_dup_norm_uid_v2(v):
            s = str(v or "").strip()
            s = s.replace("https://www.tiktok.com/@", "")
            s = s.replace("http://www.tiktok.com/@", "")
            s = s.replace("https://tiktok.com/@", "")
            s = s.replace("http://tiktok.com/@", "")
            s = s.split("?")[0].split("#")[0].split("/")[0]
            s = s.replace("@", "").strip()
            return s.lower()

        def _shared_dup_extract_uid_from_url_v2(v):
            s = str(v or "").strip()
            m = re.search(r"(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#\s]+)", s)
            if m:
                return _shared_dup_norm_uid_v2(m.group(1))
            m = re.search(r"/@([^/?#\s]+)", s)
            if m:
                return _shared_dup_norm_uid_v2(m.group(1))
            return ""

        def _shared_dup_cell_v2(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _shared_dup_header_idx_v2(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _shared_dup_row_uid_v2(ws, row):
            uid_idx = _shared_dup_header_idx_v2(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
            url_idx = _shared_dup_header_idx_v2(ws, ["プロフURL", "プロフィールURL", "profile_url", "url"], None)

            uid = _shared_dup_norm_uid_v2(_shared_dup_cell_v2(row, uid_idx))

            url_uid = ""
            if url_idx is not None:
                url_uid = _shared_dup_extract_uid_from_url_v2(_shared_dup_cell_v2(row, url_idx))

            if not url_uid and isinstance(row, (list, tuple)):
                for c in row:
                    url_uid = _shared_dup_extract_uid_from_url_v2(c)
                    if url_uid:
                        break

            return url_uid or uid

        def _shared_dup_existing_ids_v2(ws):
            uid_idx = _shared_dup_header_idx_v2(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
            url_idx = _shared_dup_header_idx_v2(ws, ["プロフURL", "プロフィールURL", "profile_url", "url"], None)

            existing = set()

            try:
                uid_values = ws.col_values(uid_idx + 1)
                for v in uid_values[1:]:
                    uid = _shared_dup_norm_uid_v2(v)
                    if uid and uid not in ["ユーザーid", "user_id", "unique_id", "id"]:
                        existing.add(uid)
            except Exception as e:
                print(f"共有シート重複防止: ユーザーID列取得エラー {str(e)[:120]}", flush=True)

            if url_idx is not None:
                try:
                    url_values = ws.col_values(url_idx + 1)
                    for v in url_values[1:]:
                        uid = _shared_dup_extract_uid_from_url_v2(v)
                        if uid:
                            existing.add(uid)
                except Exception as e:
                    print(f"共有シート重複防止: プロフURL列取得エラー {str(e)[:120]}", flush=True)

            return existing

        def _shared_dup_should_skip_v2(ws, row, existing_ids=None):
            try:
                uid = _shared_dup_row_uid_v2(ws, row)
                if not uid:
                    return "", ""
                if uid in ["ユーザーid", "user_id", "unique_id", "id"]:
                    return uid, ""

                if existing_ids is None:
                    existing_ids = _shared_dup_existing_ids_v2(ws)

                if uid in existing_ids:
                    return uid, f"共有シート重複({uid})"
                return uid, ""
            except Exception as e:
                print(f"共有シート重複防止判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_shared_dup_v2(self, values, *args, **kwargs):
            uid, reason = _shared_dup_should_skip_v2(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"shared_sheet_duplicate_guard_v2_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_shared_dup_v2(self, values, *args, **kwargs)

        def _append_rows_shared_dup_v2(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_shared_dup_v2(self, values, *args, **kwargs)

                existing_ids = _shared_dup_existing_ids_v2(self)
                filtered = []
                skipped = 0

                for row in values:
                    uid, reason = _shared_dup_should_skip_v2(self, row, existing_ids)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    if uid:
                        existing_ids.add(uid)
                    filtered.append(row)

                if not filtered:
                    return {"shared_sheet_duplicate_guard_v2_skipped_rows": skipped}

                return _orig_append_rows_shared_dup_v2(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"共有シート重複防止一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_shared_dup_v2(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_shared_dup_v2
        gspread.worksheet.Worksheet.append_rows = _append_rows_shared_dup_v2
        gspread.worksheet.Worksheet._shared_sheet_duplicate_guard_v2_patched = True

except Exception as _shared_sheet_duplicate_guard_v2_error:
    print(f"共有シート重複防止 強化パッチv2読み込みエラー: {str(_shared_sheet_duplicate_guard_v2_error)[:120]}", flush=True)
# === /共有シート重複防止 強化パッチ v2 ===


# === 色付き行の類似アカウントを落とす汎用除外パッチv2: シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_general_similar_colored_guard_v2_patched", False):
        _orig_append_row_general_similar_colored_v2 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_general_similar_colored_v2 = gspread.worksheet.Worksheet.append_rows

        _GENERAL_SIMILAR_PATTERN_WORDS_V2 = ['絡み募', '絡み募集', '地雷', 'xuhuong', 'gaixinh', 'xinhdep', 'cewek', 'wanita', 'cantik', 'mencari', 'daun muda', 'vaycongchua', 'phongcachphap', 'bachnguyetquang', 'stylenangtho', 'outfitlangman', 'cortis', 'onephony', '田島櫻子', 'slipknot', 'metal', 'affiliate', 'affiliatemarketing', 'no bio yet', 'No bio yet', '女装', '女装男子', '男の娘', '偽娘', 'ニューハーフ']
        _UNDERAGE_WORDS_V2 = ['未成年', '中学生', '高校生', 'jc', 'jc1', 'jc2', 'jc3', 'jk1', 'jk2', 'jk3', 'fjk', 'sjk', 'ljk', '15さい', '15歳', '15才', '１５さい', '１５歳', '１５才', '14さい', '14歳', '14才', '１４さい', '１４歳', '１４才', '13さい', '13歳', '13才', '１３さい', '１３歳', '１３才', '16さい', '16歳', '16才', '１６さい', '１６歳', '１６才', '17さい', '17歳', '17才', '１７さい', '１７歳', '１７才']

        def _gsc2_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _gsc2_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _gsc2_reason(ws, row):
            try:
                uid_idx = _gsc2_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _gsc2_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _gsc2_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _gsc2_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _gsc2_cell(row, uid_idx).replace("@", "")
                name = _gsc2_cell(row, name_idx)
                tags = _gsc2_cell(row, tag_idx)
                bio = _gsc2_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()
                tags_low = tags.lower()

                has_japanese = re.search(r"[ぁ-んァ-ヶ一-龥]", full) is not None
                has_kana = re.search(r"[ぁ-んァ-ヶ]", full) is not None
                has_ascii_tags = re.search(r"[a-zA-Z]", tags) is not None
                has_ascii_bio = re.search(r"[a-zA-Z]", bio) is not None

                for w in _GENERAL_SIMILAR_PATTERN_WORDS_V2:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"類似除外({ws_})"

                tags_norm_digits = tags.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                tag_tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー]+", tags_norm_digits) if t]
                if "08" in tag_tokens:
                    return uid, "ハッシュタグNG(08/未成年系)"
                if "09" in tag_tokens:
                    return uid, "ハッシュタグNG(09/未成年系)"

                for uw in _UNDERAGE_WORDS_V2:
                    uws = str(uw or "").strip()
                    if uws and uws.lower() in low:
                        return uid, f"未成年系NG({uws})"

                age_text = full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                if re.search(r"(?<![0-9])(?:1[0-7]|[0-9])\s*(?:歳|才|さい)(?![0-9])", age_text):
                    return uid, "未成年系NG(年齢表記)"

                has_litlink = ("lit.link" in low) or ("litlink" in low)
                for link in ["facebook.com", "mibextid", "onlyfans", "ofans", "fansly", "beacons.ai", "linktr.ee"]:
                    if link in low and not has_litlink:
                        return uid, f"外部リンクNG({link})"

                uid_clean = re.sub(r"[^a-zA-Z0-9]", "", uid).lower()
                uid_has_letter = re.search(r"[a-z]", uid_clean) is not None
                uid_has_digit = re.search(r"[0-9]", uid_clean) is not None
                uid_has_sep = ("_" in uid) or ("." in uid) or ("-" in uid)
                if len(uid_clean) >= 7 and uid_has_letter and uid_has_digit and not uid_has_sep:
                    if not has_kana or bio == "" or has_ascii_tags:
                        return uid, "ランダムID/海外・量産寄り"

                if has_ascii_tags and not has_japanese:
                    if bio == "" or len(bio) <= 30:
                        return uid, "外国語/海外(英字タグ中心+日本語なし)"

                if "fyp" in tags_low and not has_kana:
                    if bio == "" or has_ascii_bio or re.search(r"[\u4E00-\u9FFF]", bio):
                        return uid, "外国語/海外(fyp+日本語要素薄い)"

                cn_phrases = ["今天", "也是", "电影", "治愈", "的一天", "关注", "私信", "主页", "置顶", "找我", "美女", "漂亮", "可爱", "点赞", "评论", "转发", "视频", "大家好", "我是", "喜欢"]
                for cn in cn_phrases:
                    if cn in full:
                        return uid, f"外国語/海外(中国語:{cn})"
                simplified_chars = "这们为热电说话买卖体会觉让从给发欢乐国学广东网写气应旧后边过还进长门"
                if sum(1 for ch in simplified_chars if ch in full) >= 2:
                    return uid, "外国語/海外(中国語/簡体字)"

                if re.search(r"[\u1000-\u109F\u1780-\u17FF\u0E80-\u0EFF\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0900-\u097F]", full):
                    return uid, "外国語/海外(非日本語文字種)"

                if re.search(r"(?i)(?<![a-z])([a-z])\1{7,}(?![a-z])", tags):
                    return uid, "ハッシュタグNG(同一英字連続)"

                return uid, ""
            except Exception as e:
                print(f"色付き類似汎用除外v2判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_general_similar_colored_v2(self, values, *args, **kwargs):
            uid, reason = _gsc2_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"general_similar_colored_guard_v2_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_general_similar_colored_v2(self, values, *args, **kwargs)

        def _append_rows_general_similar_colored_v2(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_general_similar_colored_v2(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _gsc2_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"general_similar_colored_guard_v2_skipped_rows": skipped}
                return _orig_append_rows_general_similar_colored_v2(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"色付き類似汎用除外v2一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_general_similar_colored_v2(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_general_similar_colored_v2
        gspread.worksheet.Worksheet.append_rows = _append_rows_general_similar_colored_v2
        gspread.worksheet.Worksheet._general_similar_colored_guard_v2_patched = True

except Exception as _general_similar_colored_guard_v2_error:
    print(f"色付き行の類似アカウント汎用除外v2ガード読み込みエラー: {str(_general_similar_colored_guard_v2_error)[:120]}", flush=True)
# === /色付き行の類似アカウントを落とす汎用除外パッチv2 ===


# === 1650行目以降の色付きアカウントID除外: シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_colored_id_exclusion_1650_patched", False):
        _orig_append_row_colored_id_1650 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_colored_id_1650 = gspread.worksheet.Worksheet.append_rows
        _COLORED_EXCLUDED_IDS_1650 = set(['ngminhchi335', 'muxi6699', 'osakana1225', '_ll.s10', 'hozonyoudesu0', 'neko22momo', '_n0zk', 'maya181526', 'xrbdwqgoceh', 'umebosi_05', 'mio0403018', 'uu1313.t', '26zixy', 'minpuri330'])

        def _colored_id_1650_norm(v):
            s = str(v or "").strip()
            s = s.replace("https://www.tiktok.com/@", "")
            s = s.replace("https://tiktok.com/@", "")
            s = s.replace("http://www.tiktok.com/@", "")
            s = s.replace("http://tiktok.com/@", "")
            s = s.split("?")[0].split("#")[0].split("/")[0]
            return s.replace("@", "").strip()

        def _colored_id_1650_from_url(v):
            s = str(v or "").strip()
            m = re.search(r"(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#\s]+)", s)
            if m:
                return _colored_id_1650_norm(m.group(1))
            return ""

        def _colored_id_1650_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _colored_id_1650_reason(ws, row):
            try:
                uid_idx = _colored_id_1650_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                url_idx = _colored_id_1650_header_idx(ws, ["プロフURL", "プロフィールURL", "profile_url", "url"], None)
                if not isinstance(row, (list, tuple)):
                    return "", ""

                uid = _colored_id_1650_norm(row[uid_idx] if len(row) > uid_idx else "")
                url_uid = ""
                if url_idx is not None and len(row) > url_idx:
                    url_uid = _colored_id_1650_from_url(row[url_idx])
                if not url_uid:
                    for cell in row:
                        url_uid = _colored_id_1650_from_url(cell)
                        if url_uid:
                            break
                final_uid = url_uid or uid
                if final_uid and final_uid in _COLORED_EXCLUDED_IDS_1650:
                    return final_uid, f"色付き除外ID({final_uid})"
                return final_uid, ""
            except Exception as e:
                print(f"色付き除外ID1650判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_colored_id_1650(self, values, *args, **kwargs):
            uid, reason = _colored_id_1650_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"colored_id_exclusion_1650_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_colored_id_1650(self, values, *args, **kwargs)

        def _append_rows_colored_id_1650(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_colored_id_1650(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _colored_id_1650_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"colored_id_exclusion_1650_skipped_rows": skipped}
                return _orig_append_rows_colored_id_1650(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"色付き除外ID1650一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_colored_id_1650(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_colored_id_1650
        gspread.worksheet.Worksheet.append_rows = _append_rows_colored_id_1650
        gspread.worksheet.Worksheet._colored_id_exclusion_1650_patched = True

except Exception as _colored_id_1650_error:
    print(f"1650行目以降の色付きアカウントID除外パッチ読み込みエラー: {str(_colored_id_1650_error)[:120]}", flush=True)
# === /1650行目以降の色付きアカウントID除外 ===



# === NGワード追加: No bio yet シート書き込み直前ガード ===
try:
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_no_bio_yet_guard_force_patched", False):
        _orig_append_row_no_bio_yet_force = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_no_bio_yet_force = gspread.worksheet.Worksheet.append_rows

        def _no_bio_yet_force_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _no_bio_yet_force_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                for name in names:
                    if name in header:
                        return header.index(name)
            except Exception:
                pass
            return fallback

        def _no_bio_yet_force_reason(ws, row):
            try:
                uid_idx = _no_bio_yet_force_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _no_bio_yet_force_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _no_bio_yet_force_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _no_bio_yet_force_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _no_bio_yet_force_cell(row, uid_idx).replace("@", "")
                name = _no_bio_yet_force_cell(row, name_idx)
                tags = _no_bio_yet_force_cell(row, tag_idx)
                bio = _no_bio_yet_force_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio]).lower()
                if "no bio yet" in full:
                    return uid, "NGワード(No bio yet)"
                return uid, ""
            except Exception as e:
                print(f"No bio yet判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_no_bio_yet_force(self, values, *args, **kwargs):
            uid, reason = _no_bio_yet_force_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"no_bio_yet_guard_force_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_no_bio_yet_force(self, values, *args, **kwargs)

        def _append_rows_no_bio_yet_force(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_no_bio_yet_force(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _no_bio_yet_force_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"no_bio_yet_guard_force_skipped_rows": skipped}
                return _orig_append_rows_no_bio_yet_force(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"No bio yet一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_no_bio_yet_force(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_no_bio_yet_force
        gspread.worksheet.Worksheet.append_rows = _append_rows_no_bio_yet_force
        gspread.worksheet.Worksheet._no_bio_yet_guard_force_patched = True

except Exception as _no_bio_yet_guard_force_error:
    print(f"No bio yetガード読み込みエラー: {str(_no_bio_yet_guard_force_error)[:120]}", flush=True)
# === /NGワード追加: No bio yet シート書き込み直前ガード ===


# === 共有シート重複防止・最強版パッチ v3 fixed ===
# append_row / append_rows / Spreadsheet.values_append の3経路をガードし、追記直前に共有スプレッドシート全体から既存TikTok IDを再取得して重複記入を防ぐ。
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_shared_duplicate_guard_v3_fixed_patched", False):
        _orig_ws_append_row_shared_dup_v3_fixed = gspread.worksheet.Worksheet.append_row
        _orig_ws_append_rows_shared_dup_v3_fixed = gspread.worksheet.Worksheet.append_rows

        _HAS_SPREADSHEET_VALUES_APPEND_V3_FIXED = hasattr(gspread.spreadsheet.Spreadsheet, "values_append")
        if _HAS_SPREADSHEET_VALUES_APPEND_V3_FIXED:
            _orig_spreadsheet_values_append_shared_dup_v3_fixed = gspread.spreadsheet.Spreadsheet.values_append

        def _sdg3f_norm_id(value):
            s = str(value or "").strip()
            s = s.replace("＠", "@")
            s = s.replace("https://www.tiktok.com/@", "")
            s = s.replace("http://www.tiktok.com/@", "")
            s = s.replace("https://tiktok.com/@", "")
            s = s.replace("http://tiktok.com/@", "")
            s = s.split("?")[0].split("#")[0].split("/")[0]
            s = s.replace("@", "").strip().lower()
            return s

        def _sdg3f_id_from_url(value):
            s = str(value or "").strip()
            m = re.search(r"(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#\s]+)", s, flags=re.I)
            if m:
                return _sdg3f_norm_id(m.group(1))
            m = re.search(r"/@([^/?#\s]+)", s)
            if m:
                return _sdg3f_norm_id(m.group(1))
            return ""

        def _sdg3f_is_valid_id(uid):
            if not uid:
                return False
            if uid in ["ユーザーid", "user_id", "unique_id", "id", "url", "profile_url", "プロフィールurl", "プロフurl"]:
                return False
            if len(uid) < 2:
                return False
            return True

        def _sdg3f_row_candidate_ids(row):
            ids = set()
            if not isinstance(row, (list, tuple)):
                return ids

            for cell in row:
                uid = _sdg3f_id_from_url(cell)
                if _sdg3f_is_valid_id(uid):
                    ids.add(uid)

            for idx in [2, 10]:
                try:
                    uid = _sdg3f_norm_id(row[idx])
                    if _sdg3f_is_valid_id(uid) and not re.search(r"[ぁ-んァ-ヶ一-龥]", uid):
                        ids.add(uid)
                except Exception:
                    pass

            return ids

        def _sdg3f_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                lowered = [str(h or "").strip().lower() for h in header]
                for name in names:
                    if name in header:
                        return header.index(name)
                    lname = str(name).lower()
                    if lname in lowered:
                        return lowered.index(lname)
            except Exception:
                pass
            return fallback

        def _sdg3f_row_ids_with_header(ws, row):
            ids = set()
            ids |= _sdg3f_row_candidate_ids(row)
            try:
                uid_idx = _sdg3f_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                url_idx = _sdg3f_header_idx(ws, ["プロフURL", "プロフィールURL", "profile_url", "url"], 10)
                if isinstance(row, (list, tuple)):
                    if len(row) > uid_idx:
                        uid = _sdg3f_norm_id(row[uid_idx])
                        if _sdg3f_is_valid_id(uid):
                            ids.add(uid)
                    if len(row) > url_idx:
                        uid = _sdg3f_id_from_url(row[url_idx])
                        if _sdg3f_is_valid_id(uid):
                            ids.add(uid)
            except Exception:
                pass
            return ids

        def _sdg3f_get_all_worksheets_from_ws(ws):
            sheets = []
            try:
                ss = getattr(ws, "spreadsheet", None)
                if ss is not None:
                    sheets = ss.worksheets()
            except Exception:
                sheets = []
            if not sheets:
                try:
                    client = getattr(ws, "client", None)
                    spreadsheet_id = getattr(ws, "spreadsheet_id", None)
                    if client is not None and spreadsheet_id:
                        ss = client.open_by_key(spreadsheet_id)
                        sheets = ss.worksheets()
                except Exception:
                    sheets = []
            if not sheets:
                sheets = [ws]
            return sheets

        def _sdg3f_existing_ids_from_ws(ws):
            existing = set()
            try:
                worksheets = _sdg3f_get_all_worksheets_from_ws(ws)
            except Exception:
                worksheets = [ws]

            for w in worksheets:
                try:
                    rows = w.get_all_values()
                except Exception as e:
                    print(f"共有重複v3fixed: 既存行取得エラー {getattr(w, 'title', '')}: {str(e)[:120]}", flush=True)
                    continue
                for row in rows[1:]:
                    for uid in _sdg3f_row_ids_with_header(w, row):
                        if _sdg3f_is_valid_id(uid):
                            existing.add(uid)
            return existing

        def _sdg3f_existing_ids_from_spreadsheet(ss):
            existing = set()
            try:
                worksheets = ss.worksheets()
            except Exception:
                worksheets = []
            for w in worksheets:
                try:
                    rows = w.get_all_values()
                except Exception as e:
                    print(f"共有重複v3fixed: Spreadsheet既存行取得エラー {getattr(w, 'title', '')}: {str(e)[:120]}", flush=True)
                    continue
                for row in rows[1:]:
                    for uid in _sdg3f_row_ids_with_header(w, row):
                        if _sdg3f_is_valid_id(uid):
                            existing.add(uid)
            return existing

        def _sdg3f_filter_rows_by_existing(ws, rows):
            try:
                existing = _sdg3f_existing_ids_from_ws(ws)
                filtered = []
                skipped = 0
                for row in rows:
                    row_ids = _sdg3f_row_ids_with_header(ws, row)
                    hit = sorted([uid for uid in row_ids if uid in existing])
                    if hit:
                        print(f"シート書き込み直前除外: {hit[0]} / 共有シート重複v3fixed", flush=True)
                        skipped += 1
                        continue
                    for uid in row_ids:
                        if _sdg3f_is_valid_id(uid):
                            existing.add(uid)
                    filtered.append(row)
                return filtered, skipped
            except Exception as e:
                print(f"共有重複v3fixedフィルタエラー: {str(e)[:160]}", flush=True)
                return rows, 0

        def _append_row_shared_dup_v3_fixed(self, values, *args, **kwargs):
            filtered, skipped = _sdg3f_filter_rows_by_existing(self, [values])
            if not filtered:
                return {"shared_duplicate_guard_v3_fixed_skipped": True, "skipped": skipped}
            return _orig_ws_append_row_shared_dup_v3_fixed(self, filtered[0], *args, **kwargs)

        def _append_rows_shared_dup_v3_fixed(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_ws_append_rows_shared_dup_v3_fixed(self, values, *args, **kwargs)
                filtered, skipped = _sdg3f_filter_rows_by_existing(self, list(values))
                if not filtered:
                    return {"shared_duplicate_guard_v3_fixed_skipped_rows": skipped}
                return _orig_ws_append_rows_shared_dup_v3_fixed(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"共有重複v3fixed append_rowsエラー: {str(e)[:160]}", flush=True)
                return _orig_ws_append_rows_shared_dup_v3_fixed(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_shared_dup_v3_fixed
        gspread.worksheet.Worksheet.append_rows = _append_rows_shared_dup_v3_fixed
        gspread.worksheet.Worksheet._shared_duplicate_guard_v3_fixed_patched = True

        if _HAS_SPREADSHEET_VALUES_APPEND_V3_FIXED:
            def _spreadsheet_values_append_shared_dup_v3_fixed(self, range_name, params=None, body=None):
                try:
                    body = body or {}
                    rows = body.get("values") or []
                    if not isinstance(rows, list) or not rows:
                        return _orig_spreadsheet_values_append_shared_dup_v3_fixed(self, range_name, params=params, body=body)
                    existing = _sdg3f_existing_ids_from_spreadsheet(self)
                    filtered = []
                    skipped = 0
                    for row in rows:
                        row_ids = _sdg3f_row_candidate_ids(row)
                        hit = sorted([uid for uid in row_ids if uid in existing])
                        if hit:
                            print(f"シート書き込み直前除外: {hit[0]} / 共有シート重複v3fixed(values_append)", flush=True)
                            skipped += 1
                            continue
                        for uid in row_ids:
                            if _sdg3f_is_valid_id(uid):
                                existing.add(uid)
                        filtered.append(row)
                    if not filtered:
                        return {"shared_duplicate_guard_v3_fixed_values_append_skipped_rows": skipped}
                    body = dict(body)
                    body["values"] = filtered
                    return _orig_spreadsheet_values_append_shared_dup_v3_fixed(self, range_name, params=params, body=body)
                except Exception as e:
                    print(f"共有重複v3fixed values_appendエラー: {str(e)[:160]}", flush=True)
                    return _orig_spreadsheet_values_append_shared_dup_v3_fixed(self, range_name, params=params, body=body)

            gspread.spreadsheet.Spreadsheet.values_append = _spreadsheet_values_append_shared_dup_v3_fixed

except Exception as _shared_duplicate_guard_v3_fixed_error:
    print(f"共有シート重複防止・最強版パッチv3fixed読み込みエラー: {str(_shared_duplicate_guard_v3_fixed_error)[:160]}", flush=True)
# === /共有シート重複防止・最強版パッチ v3 fixed ===


# === 追加除外: 09-08系 + シャドバン + CapCut流行りダンス系 シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_teen_pair_capcut_dance_guard_patched", False):
        _orig_append_row_teen_pair_capcut = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_teen_pair_capcut = gspread.worksheet.Worksheet.append_rows

        _TEEN_PAIR_CAPCUT_WORDS = ['シャドバン', 'シャドウバン', 'げろげろぴー', 'capcut', 'tiktok流行りダンス', '流行りダンス', '流行りdance', 'unsunghero', 'runaar']

        def _tpc_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _tpc_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                lowered = [str(h or "").strip().lower() for h in header]
                for name in names:
                    if name in header:
                        return header.index(name)
                    lname = str(name).lower()
                    if lname in lowered:
                        return lowered.index(lname)
            except Exception:
                pass
            return fallback

        def _tpc_reason(ws, row):
            try:
                uid_idx = _tpc_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _tpc_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _tpc_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _tpc_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _tpc_cell(row, uid_idx).replace("@", "")
                name = _tpc_cell(row, name_idx)
                tags = _tpc_cell(row, tag_idx)
                bio = _tpc_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()

                for w in _TEEN_PAIR_CAPCUT_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"NGワード({ws_})"

                digit_text = full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                if re.search(r"(?<!\d)(?:08|09)\s*[♡❤♥💕💖/／・,，、.．\-－_\s]+\s*(?:08|09)(?!\d)", digit_text):
                    return uid, "未成年系NG(08/09ペア表記)"

                tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー♡❤♥💕💖]+", digit_text) if t]
                if "08" in tokens:
                    return uid, "未成年系NG(08)"
                if "09" in tokens:
                    return uid, "未成年系NG(09)"

                return uid, ""
            except Exception as e:
                print(f"09/08・CapCut系判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_teen_pair_capcut(self, values, *args, **kwargs):
            uid, reason = _tpc_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"teen_pair_capcut_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_teen_pair_capcut(self, values, *args, **kwargs)

        def _append_rows_teen_pair_capcut(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_teen_pair_capcut(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _tpc_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"teen_pair_capcut_guard_skipped_rows": skipped}
                return _orig_append_rows_teen_pair_capcut(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"09/08・CapCut系一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_teen_pair_capcut(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_teen_pair_capcut
        gspread.worksheet.Worksheet.append_rows = _append_rows_teen_pair_capcut
        gspread.worksheet.Worksheet._teen_pair_capcut_dance_guard_patched = True

except Exception as _teen_pair_capcut_guard_error:
    print(f"09/08・CapCut系ガード読み込みエラー: {str(_teen_pair_capcut_guard_error)[:120]}", flush=True)
# === /追加除外: 09-08系 + シャドバン + CapCut流行りダンス系 ===


# === 追加除外: 08/09末尾ID + 絵文字Bio + テンプレ/歌系タグ シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_template_song_teen_id_guard_patched", False):
        _orig_append_row_template_song_teen = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_template_song_teen = gspread.worksheet.Worksheet.append_rows
        _TEMPLATE_SONG_TEEN_NG_WORDS = ['テンプレートお借りしました', 'テンプレお借りしました', 'この歌好き', '黒毛和牛上塩タン焼680円', '黒毛和牛上塩タン焼', '村谷はるな', 'はるち']

        def _tst_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _tst_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                lowered = [str(h or "").strip().lower() for h in header]
                for name in names:
                    if name in header:
                        return header.index(name)
                    lname = str(name).lower()
                    if lname in lowered:
                        return lowered.index(lname)
            except Exception:
                pass
            return fallback

        def _tst_reason(ws, row):
            try:
                uid_idx = _tst_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _tst_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _tst_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _tst_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)

                uid = _tst_cell(row, uid_idx).replace("@", "")
                name = _tst_cell(row, name_idx)
                tags = _tst_cell(row, tag_idx)
                bio = _tst_cell(row, bio_idx)

                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()

                for w in _TEMPLATE_SONG_TEEN_NG_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"NGワード({ws_})"

                bio_without_symbols = re.sub(r"[\W_\s]+", "", bio, flags=re.UNICODE)
                emoji_or_too_short_bio = (bio == "") or (len(bio_without_symbols) == 0) or (len(bio) <= 2)
                template_song_like = re.search(r"(テンプレ|お借りしました|この歌|歌好き|流行り|流行|capcut|落書き)", full, flags=re.I) is not None

                if re.search(r"(?:08|09)$", uid) and emoji_or_too_short_bio and template_song_like:
                    return uid, "未成年/量産系NG(08/09末尾ID+短文Bio+テンプレ歌系)"

                return uid, ""
            except Exception as e:
                print(f"08/09末尾IDテンプレ歌系判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_template_song_teen(self, values, *args, **kwargs):
            uid, reason = _tst_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"template_song_teen_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_template_song_teen(self, values, *args, **kwargs)

        def _append_rows_template_song_teen(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_template_song_teen(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _tst_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"template_song_teen_guard_skipped_rows": skipped}
                return _orig_append_rows_template_song_teen(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"08/09末尾IDテンプレ歌系一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_template_song_teen(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_template_song_teen
        gspread.worksheet.Worksheet.append_rows = _append_rows_template_song_teen
        gspread.worksheet.Worksheet._template_song_teen_id_guard_patched = True

except Exception as _template_song_teen_guard_error:
    print(f"08/09末尾IDテンプレ歌系ガード読み込みエラー: {str(_template_song_teen_guard_error)[:120]}", flush=True)
# === /追加除外: 08/09末尾ID + 絵文字Bio + テンプレ/歌系タグ ===


# === 共有シート重複防止 v4: 追記後クリーンアップ ===
try:
    import re
    import time
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_duplicate_cleanup_v4_patched", False):
        _orig_append_row_dc4 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_dc4 = gspread.worksheet.Worksheet.append_rows
        _HAS_VALUES_APPEND_DC4 = hasattr(gspread.spreadsheet.Spreadsheet, "values_append")
        if _HAS_VALUES_APPEND_DC4:
            _orig_values_append_dc4 = gspread.spreadsheet.Spreadsheet.values_append

        def _dc4_norm(v):
            s = str(v or "").strip().replace("＠", "@")
            for p in ["https://www.tiktok.com/@", "http://www.tiktok.com/@", "https://tiktok.com/@", "http://tiktok.com/@"]:
                s = s.replace(p, "")
            return s.split("?")[0].split("#")[0].split("/")[0].replace("@", "").strip().lower()

        def _dc4_url_id(v):
            m = re.search(r"(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#\s]+)", str(v or ""), flags=re.I)
            return _dc4_norm(m.group(1)) if m else ""

        def _dc4_ok(uid):
            return bool(uid and len(uid) >= 2 and uid not in ["ユーザーid","user_id","unique_id","id","url","profile_url","プロフィールurl","プロフurl"])

        def _dc4_row_ids(row):
            ids = set()
            if not isinstance(row, (list, tuple)):
                return ids

            for c in row:
                u = _dc4_url_id(c)
                if _dc4_ok(u):
                    ids.add(u)

            for i in [2, 10]:
                try:
                    u = _dc4_norm(row[i])
                    if _dc4_ok(u) and not re.search(r"[ぁ-んァ-ヶ一-龥]", u):
                        ids.add(u)
                except Exception:
                    pass

            return ids

        def _dc4_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                low = [str(x or "").strip().lower() for x in header]
                for n in names:
                    if n in header:
                        return header.index(n)
                    if str(n).lower() in low:
                        return low.index(str(n).lower())
            except Exception:
                pass
            return fallback

        def _dc4_row_ids_header(ws, row):
            ids = set(_dc4_row_ids(row))
            try:
                uid_i = _dc4_header_idx(ws, ["ユーザーID","user_id","unique_id","ID","id"], 2)
                url_i = _dc4_header_idx(ws, ["プロフURL","プロフィールURL","profile_url","url"], 10)

                if len(row) > uid_i:
                    u = _dc4_norm(row[uid_i])
                    if _dc4_ok(u):
                        ids.add(u)

                if len(row) > url_i:
                    u = _dc4_url_id(row[url_i])
                    if _dc4_ok(u):
                        ids.add(u)
            except Exception:
                pass
            return ids

        def _dc4_cleanup_ws(ws, target_ids):
            try:
                target_ids = {u for u in target_ids if _dc4_ok(u)}
                if not target_ids:
                    return 0

                rows = ws.get_all_values()
                first = {}
                delete_rows = []

                for row_num, row in enumerate(rows[1:], start=2):
                    ids = _dc4_row_ids_header(ws, row)
                    for u in ids:
                        if u not in target_ids:
                            continue
                        if u not in first:
                            first[u] = row_num
                        else:
                            delete_rows.append(row_num)
                            print(f"重複行削除予定: {u} keep={first[u]} delete={row_num}", flush=True)
                            break

                deleted = 0
                for row_num in sorted(set(delete_rows), reverse=True):
                    try:
                        ws.delete_rows(row_num)
                        deleted += 1
                        print(f"重複行削除完了: row={row_num}", flush=True)
                    except Exception as e:
                        print(f"重複行削除エラー: row={row_num} {str(e)[:120]}", flush=True)

                return deleted
            except Exception as e:
                print(f"重複クリーンアップv4エラー: {str(e)[:160]}", flush=True)
                return 0

        def _dc4_cleanup_ss(ss, target_ids):
            total = 0
            try:
                for ws in ss.worksheets():
                    total += _dc4_cleanup_ws(ws, target_ids)
            except Exception as e:
                print(f"重複クリーンアップv4全体エラー: {str(e)[:160]}", flush=True)
            return total

        def _append_row_dc4(self, values, *args, **kwargs):
            target_ids = _dc4_row_ids_header(self, values)
            result = _orig_append_row_dc4(self, values, *args, **kwargs)
            if target_ids:
                time.sleep(0.5)
                _dc4_cleanup_ws(self, target_ids)
            return result

        def _append_rows_dc4(self, values, *args, **kwargs):
            target_ids = set()
            if isinstance(values, (list, tuple)):
                for row in values:
                    target_ids |= _dc4_row_ids_header(self, row)
            result = _orig_append_rows_dc4(self, values, *args, **kwargs)
            if target_ids:
                time.sleep(0.5)
                _dc4_cleanup_ws(self, target_ids)
            return result

        gspread.worksheet.Worksheet.append_row = _append_row_dc4
        gspread.worksheet.Worksheet.append_rows = _append_rows_dc4
        gspread.worksheet.Worksheet._duplicate_cleanup_v4_patched = True

        if _HAS_VALUES_APPEND_DC4:
            def _values_append_dc4(self, range_name, params=None, body=None):
                target_ids = set()
                try:
                    for row in (body or {}).get("values", []):
                        target_ids |= _dc4_row_ids(row)
                except Exception:
                    pass
                result = _orig_values_append_dc4(self, range_name, params=params, body=body)
                if target_ids:
                    time.sleep(0.5)
                    _dc4_cleanup_ss(self, target_ids)
                return result
            gspread.spreadsheet.Spreadsheet.values_append = _values_append_dc4

except Exception as _dc4_error:
    print(f"共有シート重複防止v4読み込みエラー: {str(_dc4_error)[:160]}", flush=True)
# === /共有シート重複防止 v4: 追記後クリーンアップ ===


# === 2764行目以降の色付きアカウントID除外: シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_colored_id_exclusion_2764_patched", False):
        _orig_append_row_colored_id_2764 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_colored_id_2764 = gspread.worksheet.Worksheet.append_rows
        _COLORED_EXCLUDED_IDS_2764 = set(['na_.xl72', 'm3i.64', 'o8_kko7', 'qxlyg', 'antowanett_88', 'naru13595', '14376_', '_________0.00', 'q_r__zx', 'parurun_chan1', 'sfffed55', 'o____12m', 'kuu_86369'])

        def _colored_id_2764_norm(v):
            s = str(v or "").strip()
            s = s.replace("＠", "@")
            s = s.replace("https://www.tiktok.com/@", "")
            s = s.replace("https://tiktok.com/@", "")
            s = s.replace("http://www.tiktok.com/@", "")
            s = s.replace("http://tiktok.com/@", "")
            s = s.split("?")[0].split("#")[0].split("/")[0]
            return s.replace("@", "").strip()

        def _colored_id_2764_from_url(v):
            s = str(v or "").strip()
            m = re.search(r"(?:https?://)?(?:www\.)?tiktok\.com/@([^/?#\s]+)", s, flags=re.I)
            if m:
                return _colored_id_2764_norm(m.group(1))
            return ""

        def _colored_id_2764_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                lowered = [str(h or "").strip().lower() for h in header]
                for name in names:
                    if name in header:
                        return header.index(name)
                    lname = str(name).lower()
                    if lname in lowered:
                        return lowered.index(lname)
            except Exception:
                pass
            return fallback

        def _colored_id_2764_reason(ws, row):
            try:
                uid_idx = _colored_id_2764_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                url_idx = _colored_id_2764_header_idx(ws, ["プロフURL", "プロフィールURL", "profile_url", "url"], None)

                if not isinstance(row, (list, tuple)):
                    return "", ""

                uid = _colored_id_2764_norm(row[uid_idx] if len(row) > uid_idx else "")

                url_uid = ""
                if url_idx is not None and len(row) > url_idx:
                    url_uid = _colored_id_2764_from_url(row[url_idx])

                if not url_uid:
                    for cell in row:
                        url_uid = _colored_id_2764_from_url(cell)
                        if url_uid:
                            break

                final_uid = url_uid or uid

                if final_uid and final_uid in _COLORED_EXCLUDED_IDS_2764:
                    return final_uid, f"色付き除外ID({final_uid})"

                return final_uid, ""
            except Exception as e:
                print(f"色付き除外ID2764判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_colored_id_2764(self, values, *args, **kwargs):
            uid, reason = _colored_id_2764_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"colored_id_exclusion_2764_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_colored_id_2764(self, values, *args, **kwargs)

        def _append_rows_colored_id_2764(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_colored_id_2764(self, values, *args, **kwargs)

                filtered = []
                skipped = 0

                for row in values:
                    uid, reason = _colored_id_2764_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)

                if not filtered:
                    return {"colored_id_exclusion_2764_skipped_rows": skipped}

                return _orig_append_rows_colored_id_2764(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"色付き除外ID2764一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_colored_id_2764(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_colored_id_2764
        gspread.worksheet.Worksheet.append_rows = _append_rows_colored_id_2764
        gspread.worksheet.Worksheet._colored_id_exclusion_2764_patched = True

except Exception as _colored_id_2764_error:
    print(f"2764行目以降の色付きアカウントID除外パッチ読み込みエラー: {str(_colored_id_2764_error)[:120]}", flush=True)
# === /2764行目以降の色付きアカウントID除外 ===


# === 追加NG: 学校行事・学年・未成年年齢表記 シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_school_age_ng_guard_patched", False):
        _orig_append_row_school_age_ng = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_school_age_ng = gspread.worksheet.Worksheet.append_rows
        _HAS_VALUES_APPEND_SCHOOL_AGE_NG = hasattr(gspread.spreadsheet.Spreadsheet, "values_append")
        if _HAS_VALUES_APPEND_SCHOOL_AGE_NG:
            _orig_values_append_school_age_ng = gspread.spreadsheet.Spreadsheet.values_append

        _SCHOOL_AGE_NG_WORDS = ['文化祭', '体育祭', '修学旅行', '高二', '高一', '中三', '中二', '中一', '17歳', '17才', '17サイ', '17❤︎', '17❤', '17♡', '17♥', '16歳', '16才', '16サイ', '16❤︎', '16❤', '16♡', '16♥', '15歳', '15才', '15サイ', '15❤︎', '15❤', '15♡', '15♥', '14歳', '14才', '14サイ', '14❤︎', '14❤', '14♡', '14♥', '13歳', '13才', '13サイ', '13❤︎', '13❤', '13♡', '13♥', 'えふじぇーしー', 'えすじぇーしー', 'えるじぇーしー', 'えすじぇーけー', 'えふじぇーけー', '11y', '12y', '13y', '14y', '15y', '16y', '17y']

        def _school_age_ng_cell_text(row):
            if not isinstance(row, (list, tuple)):
                return str(row or "")
            return " ".join([str(x or "") for x in row])

        def _school_age_ng_uid(row):
            try:
                if isinstance(row, (list, tuple)) and len(row) > 2:
                    return str(row[2] or "").strip().replace("@", "")
            except Exception:
                pass
            return ""

        def _school_age_ng_reason(row):
            try:
                full = _school_age_ng_cell_text(row)
                norm = full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                low = norm.lower()

                for w in _SCHOOL_AGE_NG_WORDS:
                    ws = str(w or "").strip()
                    if ws and ws.lower() in low:
                        return f"NGワード({ws})"

                if re.search(r"[\(（]\s*(?:11|12|13|14|15|16|17)\s*[\)）]", norm):
                    return "未成年系NG(括弧年齢表記)"

                if re.search(r"(?<![a-zA-Z0-9])(?:11|12|13|14|15|16|17)\s*y(?![a-zA-Z0-9])", low):
                    return "未成年系NG(11y-17y)"

                if re.search(r"(?<!\d)(?:13|14|15|16|17)\s*[❤♡♥💕💖💗💓💞]", norm):
                    return "未成年系NG(年齢+ハート表記)"

                return ""
            except Exception as e:
                print(f"学校行事/年齢NG判定エラー: {str(e)[:120]}", flush=True)
                return ""

        def _append_row_school_age_ng(self, values, *args, **kwargs):
            reason = _school_age_ng_reason(values)
            uid = _school_age_ng_uid(values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"school_age_ng_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_school_age_ng(self, values, *args, **kwargs)

        def _append_rows_school_age_ng(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_school_age_ng(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    reason = _school_age_ng_reason(row)
                    uid = _school_age_ng_uid(row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"school_age_ng_guard_skipped_rows": skipped}
                return _orig_append_rows_school_age_ng(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"学校行事/年齢NG一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_school_age_ng(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_school_age_ng
        gspread.worksheet.Worksheet.append_rows = _append_rows_school_age_ng
        gspread.worksheet.Worksheet._school_age_ng_guard_patched = True

        if _HAS_VALUES_APPEND_SCHOOL_AGE_NG:
            def _values_append_school_age_ng(self, range_name, params=None, body=None):
                try:
                    body = body or {}
                    rows = body.get("values") or []
                    if isinstance(rows, list):
                        filtered = []
                        skipped = 0
                        for row in rows:
                            reason = _school_age_ng_reason(row)
                            uid = _school_age_ng_uid(row)
                            if reason:
                                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                                skipped += 1
                                continue
                            filtered.append(row)
                        if not filtered:
                            return {"school_age_ng_values_append_skipped_rows": skipped}
                        body = dict(body)
                        body["values"] = filtered
                except Exception as e:
                    print(f"学校行事/年齢NG values_append判定エラー: {str(e)[:120]}", flush=True)
                return _orig_values_append_school_age_ng(self, range_name, params=params, body=body)

            gspread.spreadsheet.Spreadsheet.values_append = _values_append_school_age_ng

except Exception as _school_age_ng_guard_error:
    print(f"学校行事・学年・未成年年齢表記NGガード読み込みエラー: {str(_school_age_ng_guard_error)[:120]}", flush=True)
# === /追加NG: 学校行事・学年・未成年年齢表記 ===


# === 追加除外: 2764色付き行の類似アカウント汎用除外 シート書き込み直前ガード ===
try:
    import re
    import gspread

    if not getattr(gspread.worksheet.Worksheet, "_colored_similar_2764_guard_patched", False):
        _orig_append_row_colored_similar_2764 = gspread.worksheet.Worksheet.append_row
        _orig_append_rows_colored_similar_2764 = gspread.worksheet.Worksheet.append_rows
        _COLORED_SIMILAR_2764_STRONG_WORDS = ['テンプレートお借りしました', 'テンプレお借りしました', 'お借りしました', 'この歌好き', 'この音源好き', '音源好き', '黒毛和牛上塩タン焼680円', '黒毛和牛上塩タン焼', 'シャドバン', 'シャドウバン', 'シャドバン解除', 'げろげろぴー', 'unsunghero', 'runaar', '村谷はるな', 'はるち']
        _COLORED_SIMILAR_2764_GENERIC_WORDS = ['capcut', 'tiktok流行りダンス', '流行りダンス', '流行りdance', '落書き', 'fyp', 'fypシ', 'おすすめ', 'バズれ', 'バズりたい', 'テンプレ', 'この歌', 'この音源', '歌詞', '音源', 'ダンス']

        def _cs2764_cell(row, idx):
            try:
                if idx is None or not isinstance(row, (list, tuple)) or len(row) <= idx:
                    return ""
                return str(row[idx] or "").strip()
            except Exception:
                return ""

        def _cs2764_header_idx(ws, names, fallback):
            try:
                header = ws.row_values(1)
                lowered = [str(h or "").strip().lower() for h in header]
                for name in names:
                    if name in header:
                        return header.index(name)
                    lname = str(name).lower()
                    if lname in lowered:
                        return lowered.index(lname)
            except Exception:
                pass
            return fallback

        def _cs2764_reason(ws, row):
            try:
                uid_idx = _cs2764_header_idx(ws, ["ユーザーID", "user_id", "unique_id", "ID", "id"], 2)
                name_idx = _cs2764_header_idx(ws, ["表示名", "display_name", "nickname", "name"], 3)
                tag_idx = _cs2764_header_idx(ws, ["ハッシュタグ", "hashtags", "hashtag", "tag_text", "hashtag_text"], 5)
                bio_idx = _cs2764_header_idx(ws, ["プロフィール紹介文", "profile_bio", "bio", "signature", "profile_text"], 6)
                uid = _cs2764_cell(row, uid_idx).replace("@", "")
                name = _cs2764_cell(row, name_idx)
                tags = _cs2764_cell(row, tag_idx)
                bio = _cs2764_cell(row, bio_idx)
                if uid in ["ユーザーID", "user_id", "unique_id"]:
                    return "", ""

                full = " ".join([uid, name, tags, bio])
                low = full.lower()
                digit_text = full.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
                bio_without_symbols = re.sub(r"[\W_\s]+", "", bio, flags=re.UNICODE)
                bio_empty_or_emoji = (bio == "") or (len(bio_without_symbols) == 0) or (len(bio) <= 2)

                for w in _COLORED_SIMILAR_2764_STRONG_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        return uid, f"類似除外({ws_})"

                if re.search(r"(?<!\d)(?:08|09)\s*[♡❤♥💕💖/／・,，、.．\-－_\s]+\s*(?:08|09)(?!\d)", digit_text):
                    return uid, "未成年系NG(08/09ペア表記)"

                tokens = [t for t in re.split(r"[#＃\s,，、/／｜|・.．。:_\-－ー♡❤♥💕💖]+", digit_text) if t]
                if "08" in tokens:
                    return uid, "未成年系NG(08)"
                if "09" in tokens:
                    return uid, "未成年系NG(09)"

                generic_hit = None
                noise_count = 0
                for w in _COLORED_SIMILAR_2764_GENERIC_WORDS:
                    ws_ = str(w or "").strip()
                    if ws_ and ws_.lower() in low:
                        noise_count += 1
                        if generic_hit is None:
                            generic_hit = ws_

                if re.search(r"(?:08|09)$", uid) and bio_empty_or_emoji and generic_hit:
                    return uid, f"未成年/量産系NG(08/09末尾ID+短文Bio+{generic_hit})"

                if bio_empty_or_emoji and noise_count >= 2:
                    return uid, "量産系NG(短文Bio+ノイズタグ複数)"

                tags_norm = re.sub(r"\s+", "", tags.lower())
                bio_norm = re.sub(r"\s+", "", bio.lower())
                if tags_norm and tags_norm == bio_norm and generic_hit:
                    return uid, "量産系NG(ハッシュタグとBio同一)"

                return uid, ""
            except Exception as e:
                print(f"2764類似除外判定エラー: {str(e)[:120]}", flush=True)
                return "", ""

        def _append_row_colored_similar_2764(self, values, *args, **kwargs):
            uid, reason = _cs2764_reason(self, values)
            if reason:
                print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                return {"colored_similar_2764_guard_skipped": True, "uid": uid, "reason": reason}
            return _orig_append_row_colored_similar_2764(self, values, *args, **kwargs)

        def _append_rows_colored_similar_2764(self, values, *args, **kwargs):
            try:
                if not isinstance(values, (list, tuple)):
                    return _orig_append_rows_colored_similar_2764(self, values, *args, **kwargs)
                filtered = []
                skipped = 0
                for row in values:
                    uid, reason = _cs2764_reason(self, row)
                    if reason:
                        print(f"シート書き込み直前除外: {uid} / {reason}", flush=True)
                        skipped += 1
                        continue
                    filtered.append(row)
                if not filtered:
                    return {"colored_similar_2764_guard_skipped_rows": skipped}
                return _orig_append_rows_colored_similar_2764(self, filtered, *args, **kwargs)
            except Exception as e:
                print(f"2764類似除外一括判定エラー: {str(e)[:120]}", flush=True)
                return _orig_append_rows_colored_similar_2764(self, values, *args, **kwargs)

        gspread.worksheet.Worksheet.append_row = _append_row_colored_similar_2764
        gspread.worksheet.Worksheet.append_rows = _append_rows_colored_similar_2764
        gspread.worksheet.Worksheet._colored_similar_2764_guard_patched = True

except Exception as _colored_similar_2764_guard_error:
    print(f"2764類似除外ガード読み込みエラー: {str(_colored_similar_2764_guard_error)[:120]}", flush=True)
# === /追加除外: 2764色付き行の類似アカウント汎用除外 ===

