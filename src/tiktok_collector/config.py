from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os
import yaml
from dotenv import load_dotenv


@dataclass
class BrowserConfig:
    user_data_dir: str
    headless: bool
    viewport_width: int
    viewport_height: int
    start_url: str
    startup_wait_sec: int
    action_delay_sec: float
    max_runtime_minutes: int


@dataclass
class OpenAIConfig:
    api_key: str
    primary_model: str
    fallback_model: str
    use_fallback_for_uncertain: bool
    timeout_sec: int
    max_output_tokens: int
    image_detail: str


@dataclass
class GoogleSheetsConfig:
    spreadsheet_id: str
    tabs: dict
    auth_mode: str = "oauth"
    oauth_client_json: str = "./credentials/oauth_client.json"
    oauth_token_json: str = "./credentials/token.json"
    service_account_json: str = "./credentials/service_account.json"
    ng_keywords_cache_ttl_sec: int = 600


@dataclass
class SlackConfig:
    enabled: bool
    webhook_url: str


@dataclass
class RateConfig:
    max_ai_calls_per_minute: int
    target_writes_per_minute: int
    rest_every_n_posts: int
    rest_sec: int


@dataclass
class RulesConfig:
    max_followers: int
    min_followers: int
    ng_keywords: list[str]
    underage_patterns: list[str]
    foreign_strict: bool


@dataclass
class BlackbandConfig:
    send_to_ai: bool
    top_bottom_dark_ratio_threshold: float
    dark_pixel_threshold: int


@dataclass
class LoggingConfig:
    sqlite_path: str
    screenshot_dir: str


@dataclass
class AlgorithmFeedbackConfig:
    enable_negative_feedback_for_excluded: bool = True
    negative_feedback_once_per_account: bool = True
    target_only_previous_excluded: bool = True
    negative_feedback_min_interval_sec: int = 20


@dataclass
class AlgorithmStealthConfig:
    # stealth 版アルゴ。検知耐性を壊さない範囲で 2 シグナルだけ追加する。
    enable_candidacy_check: bool = True
    enable_like: bool = True
    like_probability: float = 0.05
    like_min_interval_sec: float = 90.0
    # 過去採用 uid マップ再取得の間隔(秒)。複数 PC 運用で別 PC の追記を取り込む用。
    # 書き込み二重防止は別途 _fresh_existing_uids_all_tabs で担保されているので、
    # ここは「無駄に AI を回さない」ための最適化目的。
    uid_map_refresh_sec: float = 600.0


@dataclass
class BrowserStealthConfig:
    # CDP モードの設定。1_launch_chrome.command が --remote-debugging-port=9222 で立ち上げる前提。
    cdp_url: str = "http://localhost:9222"


@dataclass
class AppConfig:
    collector_name: str
    browser: BrowserConfig
    openai: OpenAIConfig
    google_sheets: GoogleSheetsConfig
    slack: SlackConfig
    rate: RateConfig
    rules: RulesConfig
    blackband: BlackbandConfig
    logging: LoggingConfig
    algorithm_feedback: AlgorithmFeedbackConfig
    algorithm_stealth: AlgorithmStealthConfig
    browser_stealth: BrowserStealthConfig


def _get(d: dict[str, Any], path: str, default: Any = None) -> Any:
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def load_config(path: str = "config.yaml") -> AppConfig:
    load_dotenv()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("config.yaml がありません。")

    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key:
        raise RuntimeError(".env に OPENAI_API_KEY を設定してください。")

    # 環境変数 TIKTOK_MAX_FOLLOWERS が指定されていたら rules.max_followers を上書き。
    # 3_run_collector.command が起動時の対話入力でこの env を立てる。
    env_max_followers = os.getenv("TIKTOK_MAX_FOLLOWERS", "").strip()
    if env_max_followers:
        try:
            mf = int(env_max_followers)
            if mf > 0:
                raw_rules = dict(raw.get("rules", {}) or {})
                raw_rules["max_followers"] = mf
                raw["rules"] = raw_rules
        except ValueError:
            pass

    cfg = AppConfig(
        collector_name=str(raw.get("collector_name", "")),
        browser=BrowserConfig(**raw.get("browser", {})),
        openai=OpenAIConfig(
            api_key=openai_api_key,
            primary_model=_get(raw, "openai.primary_model", "gpt-4o-mini"),
            fallback_model=_get(raw, "openai.fallback_model", "gpt-4o-mini"),
            use_fallback_for_uncertain=bool(_get(raw, "openai.use_fallback_for_uncertain", True)),
            timeout_sec=int(_get(raw, "openai.timeout_sec", 20)),
            max_output_tokens=int(_get(raw, "openai.max_output_tokens", 250)),
            image_detail=str(_get(raw, "openai.image_detail", "low")),
        ),
        google_sheets=GoogleSheetsConfig(**raw.get("google_sheets", {})),
        slack=SlackConfig(**raw.get("slack", {})),
        rate=RateConfig(**raw.get("rate", {})),
        rules=RulesConfig(**raw.get("rules", {})),
        blackband=BlackbandConfig(**raw.get("blackband", {})),
        logging=LoggingConfig(**raw.get("logging", {})),
        algorithm_feedback=AlgorithmFeedbackConfig(**raw.get("algorithm_feedback", {})),
        algorithm_stealth=AlgorithmStealthConfig(**raw.get("algorithm_stealth", {})),
        browser_stealth=BrowserStealthConfig(**raw.get("browser_stealth", {})),
    )

    Path(cfg.logging.screenshot_dir).mkdir(parents=True, exist_ok=True)
    Path(cfg.logging.sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    return cfg
