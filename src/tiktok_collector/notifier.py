from __future__ import annotations
import requests


class Notifier:
    def __init__(self, cfg):
        self.enabled = bool(cfg.enabled)
        self.webhook_url = cfg.webhook_url or ""

    def send(self, text: str):
        if not self.enabled or not self.webhook_url:
            return
        try:
            requests.post(self.webhook_url, json={"text": text}, timeout=10)
        except Exception:
            pass
