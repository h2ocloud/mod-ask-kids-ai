# SPDX-License-Identifier: MIT
"""預設的假引擎：不連網、不需金鑰，用來測試裝置與協議。"""
from __future__ import annotations

import array
import math
import re

from .. import SAMPLE_RATE
from ..wavio import build_wav, parse_wav, pcm16_samples, samples_to_pcm16, WavError
from ..errors import EngineError

# 低於這個峰值就當成靜音（辨識不到語音）
SILENCE_PEAK = 200


class FakeSTT:
    """回傳固定文字；沒設定時依錄音長度回「（測試）你好」之類，靜音則回空字串。

    fixed_text 設成空字串 "" 可以模擬「辨識不到語音」。
    """

    def __init__(self, fixed_text: str | None = None) -> None:
        self.fixed_text = fixed_text

    def transcribe(self, wav: bytes, *, timeout: float | None = None) -> str:
        if self.fixed_text is not None:
            return self.fixed_text
        try:
            data = parse_wav(wav)
        except WavError as e:
            raise EngineError("fake stt got invalid wav") from e
        samples = pcm16_samples(data.pcm)
        peak = max((abs(s) for s in samples), default=0)
        if peak < SILENCE_PEAK:
            return ""
        if data.duration < 1.5:
            return "（測試）你好"
        if data.duration < 5.0:
            return "（測試）你好，今天天氣好嗎"
        return "（測試）你好，我想問一個比較長的問題"


class FakeLLM:
    """回固定格式的兒童友善回答（兩句、很短）。"""

    def complete(self, system_prompt: str, user_text: str, *,
                 timeout: float | None = None) -> str:
        # 問句裡的句號、問號換成逗號，確保回答固定是兩句
        q = re.sub(r"[。！？!?.]+", "，", user_text.strip()).strip("，, ")
        if len(q) > 40:
            q = q[:40] + "…"
        return "你問的是：%s。這是測試伺服器的假回答。" % q


# C 大調五聲音階（do re mi sol la），小朋友聽起來比較柔和
_PENTATONIC_HZ = (523.25, 587.33, 659.25, 783.99, 880.00)


class FakeTTS:
    """產生柔和的提示音旋律代替語音：一個字一個音，長度和字數成正比，音量很小。

    輸出固定是 16000 Hz／PCM16／單聲道 WAV（SERVER_API §3.2 建議的取樣率）。
    字數太多時長度會被限制（預設最長 6 秒），這只是假聲音，不需要真的唸完。
    """

    sample_rate = SAMPLE_RATE  # 固定 16000 Hz

    def __init__(self, seconds_per_char: float = 0.12, min_seconds: float = 0.8,
                 max_seconds: float = 6.0, volume: float = 0.12) -> None:
        self.seconds_per_char = seconds_per_char
        self.min_seconds = min_seconds
        self.max_seconds = max_seconds
        self.volume = volume
        self._notes = [self._note(hz) for hz in _PENTATONIC_HZ]

    def _note(self, hz: float) -> array.array:
        """一個音：0.09 秒正弦波，前後用 sin² 包絡淡入淡出避免爆音。"""
        n = int(self.sample_rate * 0.09)
        peak = 32767 * self.volume
        return array.array("h", (
            int(peak * math.sin(math.pi * i / n) ** 2
                * math.sin(2 * math.pi * hz * i / self.sample_rate))
            for i in range(n)))

    def synthesize(self, text: str, *, timeout: float | None = None) -> bytes:
        seconds = min(max(len(text.strip()) * self.seconds_per_char, self.min_seconds),
                      self.max_seconds)
        total = int(seconds * self.sample_rate)
        step = int(self.sample_rate * self.seconds_per_char)
        buf = array.array("h", bytes(total * 2))  # 先填滿靜音
        pos = 0
        for ch in text.strip():
            if pos + step > total:
                break
            if not (ch.isspace() or not ch.isalnum()):  # 標點與空白當休止符
                note = self._notes[ord(ch) % len(self._notes)]
                buf[pos:pos + len(note)] = note
            pos += step
        return build_wav(samples_to_pcm16(buf), self.sample_rate)
