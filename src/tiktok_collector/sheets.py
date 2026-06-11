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


