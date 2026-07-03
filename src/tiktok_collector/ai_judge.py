from __future__ import annotations
import base64
import json
from pathlib import Path
from openai import OpenAI


SYSTEM_PROMPT = """You judge whether a TikTok account should be collected as a potential female creator candidate based in Japan.
Return strict JSON only.

target=true only if ALL of the following hold:
1. A real female-presenting face is clearly visible.
2. It looks like a normal personal TikTok post (not fan edit, idol promotion, agency content).
3. The account appears to be based in Japan: bio or hashtags suggest Japan (Japanese text, Japanese location names, Japanese cultural references, or no clear indication of being from another country).

target=false for ANY of these (no exceptions):
- No face / body only / back view / mask or blur / face mostly covered by hair or sunglasses
- Anime, illustration, food, text-only, game screen, TV/movie/drama/YouTube repost, lyric video
- Idol or fan edit, stage performance, singing with microphone or headset, obvious external media
- Bio or hashtags are clearly written in Chinese (simplified or traditional), Korean, Vietnamese, or other non-Japanese foreign language
- Bio contains external contact info: KakaoTalk, カカオトーク, LINE ID, WeChat, Telegram, or a phone number
- Bio contains solicitation or dating phrases (e.g. 注目してください, 友達を作るのが好き, 一緒にいて安心できる人)
- The account is clearly from China, Korea, Southeast Asia, or any country outside Japan

Set uncertain=true (and target=false) when:
- Face is too small, partial, blurry, side-only, or covered to clearly verify
- Cannot tell whether this is personal vs. promo/agency content
- Bio and hashtags are entirely in a non-Japanese foreign language with no Japan-related content

Do not reject just because the video is high quality or well edited.
Do not reject just because the bio uses kanji only or has no hiragana/katakana — kanji-only Japanese bios are common.
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
        if not self.cfg.use_fallback_for_uncertain:
            return first
        # 1) uncertain のとき: 仕様通り fallback で再判定。
        # 2) target=true のとき: nano は顔・性別の誤検出が一定割合あるため、
        #    採用候補だけは保険として mini で再判定して確証を取る。
        #    fallback が target=false で返したら mini の判定を採用(誤採用を弾く)。
        if first.get("uncertain"):
            second = self.judge(image_path, metadata, fallback=True)
            second["primary_result"] = first
            return second
        return first
