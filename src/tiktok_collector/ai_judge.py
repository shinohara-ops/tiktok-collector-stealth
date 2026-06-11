from __future__ import annotations
import base64
import json
from pathlib import Path
from openai import OpenAI


SYSTEM_PROMPT = """You judge whether a TikTok account should be collected as a potential female creator candidate.
Return strict JSON only.
target=true only if a real female-presenting face is clearly visible and it looks like a normal personal TikTok post.
target=false for no face, body only, back view, mask/blur/covered face, anime, food, text-only, game, TV/movie/drama/anime/YouTube repost, lyric video, idol/fan edit, stage singing, microphone singing, pin/headset mic near mouth, or obvious external media.
Do not reject just because video is high quality or edited.
JSON keys: target boolean, uncertain boolean, cute_score integer, reason string short Japanese, has_face boolean, female_appearance boolean, external_media boolean, microphone_or_singing boolean
"""


class OpenAIJudge:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = OpenAI(api_key=cfg.api_key)

    def _image_data_url(self, path: str) -> str:
        data = Path(path).read_bytes()
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    def judge(self, image_path: str, metadata: dict, fallback: bool = False) -> dict:
        model = self.cfg.fallback_model if fallback else self.cfg.primary_model
        prompt = "Judge this TikTok candidate. Metadata JSON:\\n" + json.dumps(metadata, ensure_ascii=False)

        resp = self.client.responses.create(
            model=model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": SYSTEM_PROMPT + "\\n\\n" + prompt},
                    {"type": "input_image", "image_url": self._image_data_url(image_path), "detail": self.cfg.image_detail},
                ],
            }],
            max_output_tokens=self.cfg.max_output_tokens,
            timeout=self.cfg.timeout_sec,
        )

        raw = resp.output_text.strip()
        try:
            data = json.loads(raw)
        except Exception:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                data = json.loads(raw[start:end + 1])
            else:
                raise RuntimeError("OpenAI JSON parse failed: " + raw[:200])

        data["model_used"] = model
        return data

    def judge_with_fallback_if_needed(self, image_path: str, metadata: dict) -> dict:
        first = self.judge(image_path, metadata, fallback=False)
        if self.cfg.use_fallback_for_uncertain and first.get("uncertain"):
            second = self.judge(image_path, metadata, fallback=True)
            second["primary_result"] = first
            return second
        return first
