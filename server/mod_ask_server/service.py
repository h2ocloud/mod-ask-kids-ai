# SPDX-License-Identifier: MIT
"""問答流程（與 HTTP 無關）：STT → 兒童模式過濾 → LLM → 輸出過濾 → TTS → 紀錄。

流程重點：
- 全程有硬上限（server.hard_timeout_s，預設 15 s，SERVER_API §4），超過回 504。
- 輸入命中規則、偵測到個資：不呼叫 LLM（個資也不會送到外部 LLM），直接用安全回覆。
- 輸出命中規則：丟掉 LLM 回答，改用安全回覆。
- 以上情況都照樣回 200＋安全回覆的語音（SERVER_API §3.3）。
- STT 沒辨識出文字：預設回 200＋「我沒聽清楚，再說一次好嗎？」；可改回 422 no_speech。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from . import child_mode
from .child_mode import ChildRules
from .config import Config
from .display import DisplayRenderer
from .engines import Engines
from .errors import ApiError, EngineError, EngineTimeout
from .qa_log import QALog
from .wavio import PLAYABLE_RATES, WavData, WavError, build_wav, parse_wav

log = logging.getLogger("mod_ask.service")

# 辨識文字的字數上限（15 秒的錄音正常不到 150 字）；防止異常的 STT 結果拖慢過濾或灌爆 LLM
MAX_QUESTION_CHARS = 300


@dataclass(frozen=True)
class AskResult:
    wav: bytes
    answer_text: str
    display_bitmap: str | None  # X-Display-Bitmap 的值（base64），沒有就是 None
    filtered: bool


class Deadline:
    """整個問答流程的剩餘時間；給各引擎當逾時，用完就丟 EngineTimeout。"""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._seconds = seconds
        self._end = clock() + seconds

    def remaining(self) -> float:
        return self._end - self._clock()

    def timeout(self) -> float:
        rem = self.remaining()
        if rem <= 0:
            raise EngineTimeout("pipeline exceeded %g s" % self._seconds)
        return rem

    def check(self) -> None:
        self.timeout()


class AskService:
    def __init__(self, cfg: Config, engines: Engines, rules: ChildRules, qa_log: QALog,
                 display: DisplayRenderer | None = None) -> None:
        self.cfg = cfg
        self.engines = engines
        self.rules = rules
        self.qa_log = qa_log
        self.display = display

    def handle(self, wav: WavData, device_id: str, started: float) -> AskResult:
        """處理一段已通過驗證的錄音。started 是 time.monotonic() 的起點（算延遲用）。"""
        rules = self.rules
        deadline = Deadline(self.cfg.server.hard_timeout_s)
        upload = build_wav(wav.pcm, wav.sample_rate)  # 給 STT 的標準 WAV

        text = self._stage("stt", deadline, lambda t: self.engines.stt.transcribe(upload, timeout=t))
        text = (text or "").strip()[:MAX_QUESTION_CHARS]

        filtered = False
        question_for_log = ""
        if not any(c.isalnum() for c in text):
            # 空字串或只有標點：當成沒聽清楚
            if self.cfg.child_mode.empty_stt == "error":
                raise ApiError(422, "no_speech", "no speech recognized")
            answer = rules.reply("empty_speech")
        else:
            question_for_log = rules.mask(text)
            answer, filtered = self._answer(text, deadline)

        wav_out = self._tts(answer, deadline)
        display_bitmap = self.display.render(answer) if self.display else None

        latency_ms = int((time.monotonic() - started) * 1000)
        self.qa_log.append(device_id=device_id, question=question_for_log,
                           answer=rules.mask(answer), filtered=filtered,
                           latency_ms=latency_ms)
        return AskResult(wav=wav_out, answer_text=answer, display_bitmap=display_bitmap,
                         filtered=filtered)

    # --- 內部 ---
    def _answer(self, text: str, deadline: Deadline) -> tuple[str, bool]:
        """回傳 (回答文字, 是否被過濾)。"""
        rules = self.rules
        if rules.check_pii(text):
            return rules.reply("pii"), True
        verdict = rules.screen_input(text)
        if verdict.blocked:
            return verdict.reply or rules.reply("default"), True
        raw = self._stage("llm", deadline, lambda t: self.engines.llm.complete(
            rules.system_prompt, text, timeout=t))
        verdict = rules.screen_output(raw or "")
        if verdict.blocked:
            return verdict.reply or rules.reply("output_blocked"), True
        clipped = child_mode.clip_answer(raw or "", self.cfg.child_mode.max_answer_chars)
        if not clipped:
            return rules.reply("no_answer"), False
        return clipped, False

    def _tts(self, answer: str, deadline: Deadline) -> bytes:
        data = self._stage("tts", deadline, lambda t: self.engines.tts.synthesize(answer, timeout=t))
        try:
            out = parse_wav(data)
        except WavError:
            log.error("tts engine returned something that is not a valid WAV")
            raise ApiError(502, "upstream_failed", "tts engine returned invalid audio") from None
        # 取樣率不在裝置可播清單內就回 502，不把裝置播不了的音訊送過去（SERVER_API §3.2）
        if (out.channels != 1 or out.bits != 16
                or out.sample_rate not in PLAYABLE_RATES or out.frames == 0):
            log.error("tts engine returned unsupported audio (%d Hz, %d bit, %d ch, %d frames)",
                      out.sample_rate, out.bits, out.channels, out.frames)
            raise ApiError(502, "upstream_failed", "tts engine returned unsupported audio")
        # 重新包成標準標頭：長度欄位一定正確、去掉多餘 chunk
        return build_wav(out.pcm, out.sample_rate)

    def _stage(self, name: str, deadline: Deadline, call: Callable[[float], str | bytes]):
        """呼叫一個引擎，並把各種失敗統一轉成 504／502。"""
        try:
            result = call(deadline.timeout())
            deadline.check()
            return result
        except EngineTimeout:
            raise ApiError(504, "upstream_timeout", "%s engine timed out" % name) from None
        except EngineError as e:
            log.warning("%s engine failed: %s", name, e)
            raise ApiError(502, "upstream_failed", "%s engine failed" % name) from None
        except ApiError:
            raise
        except Exception:  # noqa: BLE001 - 自訂引擎可能丟任何例外
            log.exception("%s engine raised an unexpected error", name)
            raise ApiError(502, "upstream_failed", "%s engine failed" % name) from None

