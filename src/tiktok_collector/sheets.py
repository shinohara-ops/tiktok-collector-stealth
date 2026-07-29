from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import httplib2
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request


HEADERS = [
    "取得日時", "収集者", "ユーザーID", "表示名", "フォロワー数", "ハッシュタグ",
    "プロフィール紹介文", "可愛さ点数", "理由", "使用モデル", "プロフURL", "投稿URL", "スクショパス",
]

# 列順: A=カテゴリ B=ワード C=適用範囲 D=Bio空必須 E=有効 F=メモ
# 「有効」を右から二つ目に置き、メモを一番右(自由入力)に。
# 判定に使う 4 列(カテゴリ/ワード/scope/bio_empty)が左に集まる。
NG_KEYWORDS_HEADERS = ["カテゴリ", "ワード", "適用範囲", "Bio空必須", "有効", "メモ"]
NG_KEYWORDS_TAB_KEY = "ng_keywords"
NG_KEYWORDS_DEFAULT_TTL_SEC = 600
YELLOW_EXCLUDED_DEFAULT_TTL_SEC = 3600
EXISTING_UIDS_CACHE_TTL_SEC = 300.0
_LOCAL_WRITTEN_UIDS_PATH = Path("data/.local_written_uids.txt")
_LOCAL_WRITTEN_UIDS_MAX_AGE_HOURS = 24.0

NG_COL_CATEGORY = 0
NG_COL_WORD = 1
NG_COL_SCOPE = 2
NG_COL_BIO_EMPTY = 3
NG_COL_ENABLED = 4
NG_COL_MEMO = 5

# プルダウン候補(日本語)。strict=False にしているので旧英語値(general / TRUE 等)
# が残っていてもエラーにならない。新規入力は日本語ラベルから選ぶ。
NG_DROPDOWN_CATEGORIES = ["汎用", "NG", "広告", "公式", "事務所", "配信", "音楽", "ゲーム", "ペット", "食べ物"]
NG_DROPDOWN_SCOPE = ["全体", "ハッシュタグ", "Bio"]
NG_DROPDOWN_BIO_EMPTY = ["必須", "不要"]
NG_DROPDOWN_ENABLED = ["有効", "無効"]
NG_DROPDOWN_SPECS: list[tuple[int, list[str], bool]] = [
    (NG_COL_CATEGORY, NG_DROPDOWN_CATEGORIES, False),
    (NG_COL_SCOPE, NG_DROPDOWN_SCOPE, False),
    (NG_COL_BIO_EMPTY, NG_DROPDOWN_BIO_EMPTY, False),
    (NG_COL_ENABLED, NG_DROPDOWN_ENABLED, False),
]
NG_DROPDOWN_ROWS = 5000

# 日本語ラベル ↔ 内部表現の対応。
NG_CATEGORY_JA_TO_EN = {
    "汎用": "general",
    "NG": "ng", "ng": "ng",
    "広告": "ad",
    "公式": "official",
    "事務所": "agency",
    "配信": "live",
    "音楽": "music",
    "ゲーム": "game",
    "ペット": "pet",
    "食べ物": "food",
}
NG_SCOPE_JA_TO_EN = {
    "全体": "all", "all": "all",
    "ハッシュタグ": "hashtag", "hashtag": "hashtag",
    "Bio": "bio", "bio": "bio",
}
# どちらの列でも「ON」「TRUE」相当はここ、「OFF」「FALSE」相当はその下にまとめる。
_NG_TRUTHY_LOWER = {"有効", "必須", "true", "1", "yes", "on"}
_NG_FALSEY_LOWER = {"無効", "不要", "false", "0", "no", "off"}

# 適用範囲(E列)の値: all = bio + hashtags + display_name など全部を結合した text に部分一致(現状互換)
#                    hashtag = ハッシュタグだけに部分一致
#                    bio = Bio だけに部分一致
NG_SCOPE_VALUES = {"all", "hashtag", "bio"}


def _is_yellow_bg(bg: dict) -> bool:
    """Google Sheets API の backgroundColor dict から黄色系かどうかを判定。
    色コンポーネントが 0 のとき API はキーを省略する(デフォルト 0)。
    そのため get('blue', 0.0) とする(1.0 にすると省略=0 を白と誤判定する)。
    空 dict (色指定なし) は False を返す。
    """
    if not bg:
        return False
    r = float(bg.get("red", 0.0))
    g = float(bg.get("green", 0.0))
    b = float(bg.get("blue", 0.0))   # 省略 = 0
    return r >= 0.75 and g >= 0.70 and b <= 0.50


def _ng_is_truthy(s: str) -> bool:
    return s.strip().lower() in _NG_TRUTHY_LOWER or s.strip() in _NG_TRUTHY_LOWER


def _ng_is_falsey(s: str) -> bool:
    return s.strip().lower() in _NG_FALSEY_LOWER or s.strip() in _NG_FALSEY_LOWER

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self._creds = self._load_credentials()
        self._http = httplib2.Http(timeout=15)
        authorized_http = AuthorizedHttp(self._creds, http=self._http)
        self.service = build("sheets", "v4", http=authorized_http)
        # httplib2 はスレッドセーフでないため、バックグラウンドスレッドには
        # threading.local で独立した service/Http インスタンスを持たせる。
        self._thread_local = threading.local()
        self._http_lock = threading.Lock()  # メインスレッドの _http 用
        self.spreadsheet_id = cfg.spreadsheet_id
        self.tabs = cfg.tabs
        self._ng_cache: dict[str, list[str]] = {}
        self._ng_meta_cache: dict[str, list[dict]] = {}
        self._ng_cache_ts: float = 0.0
        self._ng_cache_ttl: float = float(getattr(cfg, "ng_keywords_cache_ttl_sec", NG_KEYWORDS_DEFAULT_TTL_SEC) or NG_KEYWORDS_DEFAULT_TTL_SEC)
        self._yellow_excluded_cache: frozenset[str] = frozenset()
        self._yellow_excluded_cache_ts: float = 0.0
        self._yellow_excluded_ttl: float = float(getattr(cfg, "yellow_excluded_cache_ttl_sec", YELLOW_EXCLUDED_DEFAULT_TTL_SEC) or YELLOW_EXCLUDED_DEFAULT_TTL_SEC)
        self._existing_uids_cache: set[str] = set()
        self._existing_uids_cache_ts: float = 0.0
        self._existing_recommended_uids_cache: set[str] = set()
        self._existing_recommended_uids_cache_ts: float = 0.0
        self._existing_uids_lock = threading.Lock()
        # セッション内で書き込み済みの UID を記録する。TTL キャッシュとは独立して
        # 同セッション内の二重書き込みを確実に防ぐ最終防衛線。
        # ★ Chrome 再起動をまたいでも重複しないよう、起動時にディスクキャッシュから復元する。
        self._session_written_uids: set[str] = set()
        # _append_to_tab の「チェック→書き込み」をアトミックにするロック。
        # 複数スレッドが同時に同じ uid を書き込もうとしても、ロックで直列化する。
        self._append_lock = threading.Lock()
        self._local_written_uids_lock = threading.Lock()
        self._load_local_written_uids()
        self._load_ng_disk_cache()
        # _ensure_tabs() はタブ/ヘッダー/フォーマットの初回セットアップ用で
        # 1回あたり20〜40 API コールを発生させる。毎起動で呼ぶと複数PC運用時に
        # Google Sheets API の 429 レート制限を引き起こす根本原因になる。
        # .tabs_ready フラグが存在すれば「セットアップ済み」としてスキップする。
        _tabs_ready_flag = Path("data/.tabs_ready")
        if _tabs_ready_flag.exists():
            print("Google Sheets タブ確認スキップ(セットアップ済み)", flush=True)
        else:
            try:
                self._ensure_tabs()
                _tabs_ready_flag.parent.mkdir(parents=True, exist_ok=True)
                _tabs_ready_flag.touch()
                print("Google Sheets タブ確認OK → .tabs_ready を作成しました", flush=True)
            except Exception as e:
                # 失敗してもタブが既に存在する場合は収集を続行できる。
                print(f"⚠ Google Sheets 起動時タブ確認に失敗しました(収集は続行):", flush=True)
                print(f"  {str(e)[:120]}", flush=True)
                print("  → タブの再確認が必要な場合は data/.tabs_ready を削除して再起動してください。", flush=True)

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
        import os
        client_path = Path(getattr(self.cfg, "oauth_client_json", "./credentials/oauth_client.json"))
        token_path = Path(getattr(self.cfg, "oauth_token_json", "./credentials/token.json"))
        token_path.parent.mkdir(parents=True, exist_ok=True)

        creds = None
        if token_path.exists():
            creds = OAuthCredentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as _ref_err:
                # token.json を削除しない: AuthorizedHttp が次回 API コール時に再試行する。
                # 削除 + run_local_server 呼び出しは非対話モードでの永久ハングにつながる。
                print(f"Google認証トークン更新失敗(続行): {str(_ref_err)[:120]}", flush=True)

        if not creds or not creds.valid:
            if not client_path.exists():
                raise FileNotFoundError("credentials/oauth_client.json がありません。import_google_oauth_json.command を実行してください。")
            # 非対話モード(overnight運用)では run_local_server を呼ばない。
            # 呼ぶとユーザー操作待ちで永久にハングする。
            if os.environ.get("TIKTOK_NONINTERACTIVE") == "1":
                raise RuntimeError(
                    "Google OAuth 認証トークンが無効です。非対話モードでは再認証できません。\n"
                    "先に 3_run_collector.command を対話モードで起動して認証してください。"
                )
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

        # 採用書き込みの帯域別タブも保証する(空 list なら no-op)。
        self._ensure_recommended_range_tabs()

        self._format_tabs()

    def _recommended_range_tab_names(self) -> list[str]:
        """config.google_sheets.recommended_tab_ranges からタブ名を取り出す。"""
        raw = getattr(self.cfg, "recommended_tab_ranges", []) or []
        out: list[str] = []
        for entry in raw:
            if isinstance(entry, dict):
                name = entry.get("name") or ""
            else:
                name = ""
            if name:
                out.append(name)
        return out

    def _resolve_recommended_tab_name(self, follower_count) -> str:
        """`follower_count` から該当帯域タブ名を返す。
        範囲未設定 / 範囲外 / fc 不明時は `tabs.recommended` にフォールバック。
        半開区間 [min, max)。
        """
        default = self.tabs.get("recommended", "おすすめ")
        raw = getattr(self.cfg, "recommended_tab_ranges", []) or []
        if not raw:
            return default
        try:
            if follower_count is None or str(follower_count) == "":
                return default
            fc = int(follower_count)
        except (TypeError, ValueError):
            return default
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            try:
                lo = int(entry.get("min", 0))
                hi = int(entry.get("max", 0))
            except (TypeError, ValueError):
                continue
            name = entry.get("name") or ""
            if name and lo <= fc < hi:
                return name
        return default

    def _ensure_recommended_range_tabs(self) -> None:
        """帯域別タブが無ければ作成 + ヘッダー設定。既存「おすすめ」と同じ HEADERS。"""
        names = self._recommended_range_tab_names()
        if not names:
            return
        existing = self._get_sheet_titles()
        requests = []
        for name in names:
            if name not in existing:
                requests.append({"addSheet": {"properties": {"title": name}}})
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": requests},
            ).execute()
        for name in names:
            self._ensure_header(name)

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
        existing = values[0] if values else []
        if not existing:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=rng,
                valueInputOption="RAW",
                body={"values": [header_cols]},
            ).execute()
        elif len(existing) < len(header_cols):
            # 既存ヘッダーが短いとき、不足列だけを後ろに追加(既存セルは触らない)
            missing_start = len(existing)
            missing_cols = header_cols[missing_start:]
            start_col = chr(ord("A") + missing_start)
            missing_rng = f"{tab}!{start_col}1:{col_end}1"
            print(f"ヘッダー拡張: tab={tab} +{missing_cols}", flush=True)
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=missing_rng,
                valueInputOption="RAW",
                body={"values": [missing_cols]},
            ).execute()

        if ng_tab and tab == ng_tab:
            self._ensure_ng_dropdowns(tab)

    def _ensure_ng_dropdowns(self, tab: str) -> None:
        """NG タブの A/C/E/F 列にプルダウン(データ検証)を設定する。
        ワード(B)とメモ(D)は自由入力のままにする。

        Sheets のデータ検証は行挿入/削除で範囲が一緒にずれる挙動があるので、
        idempotent にするためにまず該当 4 列の **全範囲のデータ検証をクリア** し、
        そのうえで 2 行目以降にだけ再設定する。これでヘッダー行に古いルールが
        残るケースを確実に潰せる。
        """
        sheet_id = self._sheet_id_by_title().get(tab)
        if sheet_id is None:
            return
        clear_requests = []
        apply_requests = []
        for col_index, options, strict in NG_DROPDOWN_SPECS:
            clear_requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": NG_DROPDOWN_ROWS,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    },
                    # rule を省略 = データ検証クリア
                },
            })
            apply_requests.append({
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,  # 0-based: 2 行目から
                        "endRowIndex": NG_DROPDOWN_ROWS,
                        "startColumnIndex": col_index,
                        "endColumnIndex": col_index + 1,
                    },
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": v} for v in options],
                        },
                        "showCustomUi": True,
                        "strict": strict,
                    },
                },
            })
        if clear_requests or apply_requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": clear_requests + apply_requests},
            ).execute()

    def _format_tabs(self):
        # 折り返しで行の縦幅が広がる問題を防ぐ
        ids = self._sheet_id_by_title()
        ng_tab = self.tabs.get(NG_KEYWORDS_TAB_KEY)
        requests = []
        # メイン tabs + 帯域別タブをまとめて整形。重複名は 1 回だけ処理。
        target_tabs = list(self.tabs.values()) + self._recommended_range_tab_names()
        seen_format_tabs: set[str] = set()
        for tab in target_tabs:
            if tab in seen_format_tabs:
                continue
            seen_format_tabs.add(tab)
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
        帯域別タブ(recommended_tab_ranges)は全て "recommended" 扱いでマージする。
        """
        status_map = {}
        tab_status = {
            "recommended": "recommended",
            "skipped": "skipped",
            "blackband": "blackband",
            "pending": "pending",
        }
        scanned: set[str] = set()
        for key, tab in self.tabs.items():
            if str(key) == NG_KEYWORDS_TAB_KEY:
                # NGワードタブは候補ログではないのでスキップ
                continue
            scanned.add(tab)
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
        # 帯域別おすすめタブをすべて "recommended" 扱いで追加。
        for tab in self._recommended_range_tab_names():
            if tab in scanned:
                continue
            scanned.add(tab)
            try:
                resp = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{tab}!C2:C"
                ).execute()
                for row in resp.get("values", []):
                    if row and str(row[0]).strip():
                        uid = str(row[0]).strip().replace("@", "")
                        if uid and uid not in ["ユーザーID", "user_id", "unique_id"]:
                            status_map[uid] = "recommended"
            except Exception:
                pass
        return status_map

    def _reset_http_connections(self) -> None:
        """httplib2 のコネクションプールをクリアして次回リクエストで新規接続を強制する。
        SSL/タイムアウトエラー(サーバー側が接続を切った後の再利用)の回復に使う。"""
        try:
            with self._http_lock:
                self._http.connections.clear()
        except Exception:
            pass
        # バックグラウンドスレッドのコネクションもクリア
        try:
            h = getattr(self._thread_local, 'http', None)
            if h is not None:
                h.connections.clear()
        except Exception:
            pass

    def _get_bg_service(self):
        """バックグラウンドスレッド専用の service インスタンスを返す。
        threading.local でスレッドごとに独立した httplib2.Http を持つため
        メインスレッドの self.service と競合しない。"""
        if not hasattr(self._thread_local, 'service'):
            self._thread_local.http = httplib2.Http(timeout=15)
            self._thread_local.service = build(
                "sheets", "v4",
                http=AuthorizedHttp(self._creds, http=self._thread_local.http),
            )
        return self._thread_local.service

    def _normalize_uid_for_dedupe(self, value) -> str:
        return str(value or "").strip().replace("@", "")

    def _fresh_existing_uids_all_tabs(self) -> set[str]:
        """
        別PCの追記も拾うため、共有シート全タブのユーザーID列を取得する。
        EXISTING_UIDS_CACHE_TTL_SEC 以内は API を叩かずメモリキャッシュを返す。
        """
        with self._existing_uids_lock:
            if self._existing_uids_cache_ts and (time.time() - self._existing_uids_cache_ts) < EXISTING_UIDS_CACHE_TTL_SEC:
                return set(self._existing_uids_cache)
        uids = set()
        scan_tabs = list(self.tabs.values()) + self._recommended_range_tab_names()
        seen_tabs: set[str] = set()
        consec_errors = 0
        cut_short = False
        for tab in scan_tabs:
            if tab in seen_tabs:
                continue
            seen_tabs.add(tab)
            last_exc = None
            for attempt in range(2):
                try:
                    resp = self._get_bg_service().spreadsheets().values().get(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{tab}!C2:C"
                    ).execute()
                    for row in resp.get("values", []):
                        if row and str(row[0]).strip():
                            uid = self._normalize_uid_for_dedupe(row[0])
                            if uid and uid not in {"ユーザーID", "user_id", "unique_id", "ID", "id"}:
                                uids.add(uid)
                    consec_errors = 0
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt == 0:
                        self._reset_http_connections()
                        wait = 60 if "429" in str(e) else 10
                        time.sleep(wait)
            if last_exc is not None:
                print(f"記入直前の共有既出チェック取得エラー: tab={tab} error={str(last_exc)[:120]}", flush=True)
                consec_errors += 1
                if consec_errors >= 2:
                    print("Sheets 連続エラー: 既出チェックを打ち切ります(ネットワーク障害の可能性)", flush=True)
                    cut_short = True
                    break
        with self._existing_uids_lock:
            if cut_short:
                # エラーで打ち切った場合は古いキャッシュを保持し、tsだけ更新して再ハンマリングを防ぐ
                self._existing_uids_cache_ts = time.time()
            else:
                self._existing_uids_cache = uids
                self._existing_uids_cache_ts = time.time()
        return self._existing_uids_cache if cut_short else uids

    def _fresh_existing_recommended_uids(self, force_refresh: bool = False) -> set[str]:
        """採用書き込み専用の重複チェック。「おすすめ」+ 帯域別タブだけスキャン。
        除外ログを含めると「過去除外 → AI 救出 → 再採用」のパスで毎回重複扱いされ、
        Sheets には書かれず終わる。除外ログにあっても、おすすめ系タブに未登録なら
        書き込み OK。EXISTING_UIDS_CACHE_TTL_SEC 以内はキャッシュを返す。
        force_refresh=True なら TTL を無視して必ず最新を取得する。
        """
        if not force_refresh:
            with self._existing_uids_lock:
                if self._existing_recommended_uids_cache_ts and (time.time() - self._existing_recommended_uids_cache_ts) < EXISTING_UIDS_CACHE_TTL_SEC:
                    return set(self._existing_recommended_uids_cache)
        uids: set[str] = set()
        scan_tabs: list[str] = []
        main_rec = self.tabs.get("recommended")
        if main_rec:
            scan_tabs.append(main_rec)
        scan_tabs.extend(self._recommended_range_tab_names())
        seen_tabs: set[str] = set()
        consec_errors = 0
        cut_short = False
        for tab in scan_tabs:
            if tab in seen_tabs:
                continue
            seen_tabs.add(tab)
            last_exc = None
            for attempt in range(2):
                try:
                    resp = self._get_bg_service().spreadsheets().values().get(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{tab}!C2:C"
                    ).execute()
                    for row in resp.get("values", []):
                        if row and str(row[0]).strip():
                            uid = self._normalize_uid_for_dedupe(row[0])
                            if uid and uid not in {"ユーザーID", "user_id", "unique_id", "ID", "id"}:
                                uids.add(uid)
                    consec_errors = 0
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt == 0:
                        self._reset_http_connections()
                        wait = 60 if "429" in str(e) else 10
                        time.sleep(wait)
            if last_exc is not None:
                print(f"記入直前のおすすめ既出チェック取得エラー: tab={tab} error={str(last_exc)[:120]}", flush=True)
                consec_errors += 1
                if consec_errors >= 2:
                    print("Sheets 連続エラー: おすすめ既出チェックを打ち切ります(ネットワーク障害の可能性)", flush=True)
                    cut_short = True
                    break
        with self._existing_uids_lock:
            if cut_short:
                self._existing_recommended_uids_cache_ts = time.time()
            else:
                self._existing_recommended_uids_cache = uids
                self._existing_recommended_uids_cache_ts = time.time()
        return self._existing_recommended_uids_cache if cut_short else uids

    def _is_duplicate_uid_before_append(self, uid: str, scope: str = "all", force_refresh: bool = False) -> bool:
        uid = self._normalize_uid_for_dedupe(uid)
        if not uid:
            return False
        if scope == "recommended_only":
            existing = self._fresh_existing_recommended_uids(force_refresh=force_refresh)
        else:
            existing = self._fresh_existing_uids_all_tabs()
        return uid in existing

    def append(self, tab_key: str, row: list):
        tab = self.tabs[tab_key]
        return self._append_to_tab(tab, row)

    def append_recommended(self, row: list, follower_count) -> dict:
        """採用書き込み専用。follower_count に応じて帯域別タブを選ぶ。
        重複チェックは「おすすめ系タブのみ」(除外ログを含めない)。
        過去除外を AI が救出するケースで、除外ログに残った uid が
        二重書き込み判定に巻き込まれて Sheets に何も書かれない現象を回避する。
        """
        tab = self._resolve_recommended_tab_name(follower_count)
        return self._append_to_tab(tab, row, dup_scope="recommended_only")

    def _append_to_tab(self, tab: str, row: list, dup_scope: str = "all"):
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

        # _append_lock で「重複チェック → 書き込み」をアトミックにする。
        # ロックなしだと2スレッドが同時にチェックを通過して両方書き込む競合が起きる。
        with self._append_lock:
            if uid and uid in self._session_written_uids:
                print(f"[SESSION_DUPLICATE_SKIP] user_id={uid} tab={tab}", flush=True)
                return {"duplicate_skipped": True, "uid": uid, "tab": tab}

            if uid and self._is_duplicate_uid_before_append(uid, scope=dup_scope):
                print(f"[PRE_APPEND_DUPLICATE_SKIP] user_id={uid} tab={tab} scope={dup_scope}", flush=True)
                self._session_written_uids.add(uid)
                return {"duplicate_skipped": True, "uid": uid, "tab": tab}

            if not row[0]:
                row[0] = "'" + datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            elif not str(row[0]).startswith("'"):
                row[0] = "'" + str(row[0])

            # execute() が例外を投げても書き込みが届いていた場合があるため、
            # 送信前にセッションセットへ楽観的追加する。
            # 429(サーバーが拒否)は確実に未書き込みなので例外時に取り消す。
            if uid:
                self._session_written_uids.add(uid)
            try:
                result = self._get_bg_service().spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{tab}!A:M",
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                ).execute()
            except Exception as e:
                if uid and "429" in str(e):
                    # 429 = サーバーが拒否したので次回リトライを許可する
                    self._session_written_uids.discard(uid)
                elif uid:
                    # タイムアウト等 429 以外は書き込みがサーバー側で届いた可能性あり
                    # → ディスクキャッシュに即保存してプロセス再起動後の二重書き込みを防ぐ
                    self._save_local_written_uid(uid)
                raise
            if uid:
                with self._existing_uids_lock:
                    self._existing_uids_cache.add(uid)
                    self._existing_recommended_uids_cache.add(uid)
                self._save_local_written_uid(uid)
            return result

    def _load_local_written_uids(self) -> None:
        """data/.local_written_uids.txt から書き込み済み UID を復元する。
        Chrome 再起動後でも _session_written_uids が引き継がれ、重複書き込みを防ぐ。
        ファイルが 24 時間以上古い場合は削除してリセットする。"""
        try:
            p = _LOCAL_WRITTEN_UIDS_PATH
            if not p.exists():
                return
            age_hours = (time.time() - p.stat().st_mtime) / 3600
            if age_hours > _LOCAL_WRITTEN_UIDS_MAX_AGE_HOURS:
                try:
                    p.unlink()
                except Exception:
                    pass
                return
            loaded = 0
            for line in p.read_text(encoding="utf-8").splitlines():
                uid = line.strip()
                if uid:
                    self._session_written_uids.add(uid)
                    loaded += 1
            if loaded:
                print(f"ローカル書き込みキャッシュ読込: {loaded}件(重複防止)", flush=True)
        except Exception:
            pass

    def _save_local_written_uid(self, uid: str) -> None:
        """書き込み成功した UID をディスクに追記する(再起動後の重複防止用)。"""
        if not uid:
            return
        try:
            with self._local_written_uids_lock:
                _LOCAL_WRITTEN_UIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
                with _LOCAL_WRITTEN_UIDS_PATH.open("a", encoding="utf-8") as f:
                    f.write(uid + "\n")
        except Exception:
            pass

    _NG_DISK_CACHE_PATH = Path("data/.ng_cache.json")

    def _load_ng_disk_cache(self) -> None:
        """main.py 再起動をまたいでNGワードキャッシュを引き継ぐ。
        ディスクキャッシュが TTL 内なら Sheets へのリクエストを省く。"""
        try:
            if not self._NG_DISK_CACHE_PATH.exists():
                return
            payload = json.loads(self._NG_DISK_CACHE_PATH.read_text(encoding="utf-8"))
            saved_ts = float(payload.get("ts", 0))
            if time.time() - saved_ts >= self._ng_cache_ttl:
                return  # 期限切れ
            self._ng_cache = payload.get("flat", {})
            self._ng_meta_cache = payload.get("meta", {})
            self._ng_cache_ts = saved_ts
            print(f"NGワードディスクキャッシュ読込: {sum(len(v) for v in self._ng_cache.values())}語", flush=True)
        except Exception:
            pass

    def _save_ng_disk_cache(self) -> None:
        try:
            self._NG_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._NG_DISK_CACHE_PATH.write_text(
                json.dumps({"ts": self._ng_cache_ts, "flat": self._ng_cache, "meta": self._ng_meta_cache}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def _refresh_ng_caches(self) -> None:
        """Sheets「NGワード」タブを1回 fetch して _ng_cache と _ng_meta_cache を同時に更新。
        失敗時は直前キャッシュを保持(ts を更新しないので次回再試行できる)。
        列: A=カテゴリ, B=ワード, C=有効, D=メモ, E=適用範囲, F=Bio空必須
        E/F が空欄なら all / FALSE のデフォルト(=現状互換)。
        """
        now = time.time()
        if self._ng_cache_ts and (now - self._ng_cache_ts) < self._ng_cache_ttl:
            return

        tab = self.tabs.get(NG_KEYWORDS_TAB_KEY)
        if not tab:
            self._ng_cache = {}
            self._ng_meta_cache = {}
            self._ng_cache_ts = now
            return

        try:
            resp = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"{tab}!A2:F",
            ).execute()
        except Exception as e:
            # 読込失敗時は前回キャッシュにフォールバック。
            # 429(レート制限)のときは ts を更新して TTL 内は再試行しない。
            # ts を更新しないと候補ごとに即リトライして 429 を連発し続けるため。
            print(f"NGワード読込失敗(キャッシュ流用): {str(e)[:160]}", flush=True)
            if "429" in str(e):
                self._ng_cache_ts = now
            return

        rows = resp.get("values", []) or []
        flat: dict[str, list[str]] = {}
        meta: dict[str, list[dict]] = {}

        def _cell(row: list, idx: int) -> str:
            return str(row[idx]).strip() if len(row) > idx and row[idx] is not None else ""

        for row in rows:
            if len(row) <= NG_COL_WORD:
                continue
            category_raw = _cell(row, NG_COL_CATEGORY)
            # 日本語表示("汎用")も英語値("general")も同じ内部キーに正規化
            category = NG_CATEGORY_JA_TO_EN.get(category_raw, category_raw.lower())
            word = _cell(row, NG_COL_WORD)
            if not category or not word:
                continue
            enabled_raw = _cell(row, NG_COL_ENABLED)
            if enabled_raw and _ng_is_falsey(enabled_raw):
                continue

            scope_raw = _cell(row, NG_COL_SCOPE)
            scope_norm = NG_SCOPE_JA_TO_EN.get(scope_raw, scope_raw.lower())
            scope = scope_norm if scope_norm in NG_SCOPE_VALUES else "all"

            bio_empty_raw = _cell(row, NG_COL_BIO_EMPTY)
            bio_empty_required = _ng_is_truthy(bio_empty_raw)

            flat.setdefault(category, []).append(word)
            meta.setdefault(category, []).append({
                "word": word,
                "scope": scope,
                "bio_empty_required": bio_empty_required,
                "category": category,
            })

        self._ng_cache = flat
        self._ng_meta_cache = meta
        self._ng_cache_ts = now
        self._save_ng_disk_cache()

    def get_ng_keywords(self) -> dict[str, list[str]]:
        """カテゴリ別の単語リストを返す(後方互換 API)。
        メタ情報(scope / bio_empty_required)が必要なら get_ng_keywords_with_meta を使う。"""
        self._refresh_ng_caches()
        return self._ng_cache

    def get_ng_keywords_with_meta(self) -> dict[str, list[dict]]:
        """カテゴリ別のメタ付きワードリストを返す。各エントリ:
            {"word": str, "scope": "all"|"hashtag"|"bio",
             "bio_empty_required": bool, "category": str}
        """
        self._refresh_ng_caches()
        return self._ng_meta_cache

    def get_yellow_excluded_uids(self) -> frozenset[str]:
        """config の yellow_excluded_tab / yellow_excluded_start_row で指定した
        シートの start_row 行目以降を取得し、黄色背景セルを持つ行のユーザーID(列C)を返す。
        TTL(デフォルト1時間)内は前回フェッチ結果を再利用する。
        tab が空 / start_row が 0 の場合は空 frozenset を返す(=無効)。
        """
        tab = str(getattr(self.cfg, "yellow_excluded_tab", "") or "").strip()
        start_row = int(getattr(self.cfg, "yellow_excluded_start_row", 0) or 0)
        if not tab or start_row <= 0:
            return frozenset()

        now = time.time()
        if self._yellow_excluded_cache_ts and (now - self._yellow_excluded_cache_ts) < self._yellow_excluded_ttl:
            return self._yellow_excluded_cache

        range_notation = f"'{tab}'!A{start_row}:M"
        try:
            response = self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                ranges=[range_notation],
                includeGridData=True,
            ).execute()
        except Exception as e:
            # 429 のときは ts を更新して TTL 内は再試行しない(連発防止)
            print(f"黄色除外ID読込失敗(キャッシュ流用): {str(e)[:160]}", flush=True)
            if "429" in str(e):
                self._yellow_excluded_cache_ts = now
            return self._yellow_excluded_cache

        uids: set[str] = set()
        for sheet in response.get("sheets", []):
            for data_range in sheet.get("data", []):
                for row_data in data_range.get("rowData", []):
                    values = row_data.get("values", [])
                    row_is_yellow = any(
                        _is_yellow_bg(
                            (cell.get("userEnteredFormat") or {}).get("backgroundColor") or {}
                        )
                        for cell in values
                    )
                    if not row_is_yellow:
                        continue
                    if len(values) <= 2:
                        continue
                    # 列C(0-indexed=2)がユーザーID
                    uid_val = str(values[2].get("formattedValue", "")).strip().replace("@", "")
                    if uid_val and uid_val not in {"ユーザーID", "user_id", "unique_id"}:
                        uids.add(uid_val)

        self._yellow_excluded_cache = frozenset(uids)
        self._yellow_excluded_cache_ts = now
        print(f"黄色除外ID読込: {len(uids)}件 from {tab}!A{start_row}:M", flush=True)
        return self._yellow_excluded_cache


