# SPDX-License-Identifier: MIT
"""STT／LLM／TTS 的可替換介面（typing.Protocol，結構化比對，不必繼承）。

換引擎＝寫一個有對應方法的物件，再用設定檔的 "custom" 指到它的工廠函式
（見 README「換引擎」）。引擎遇到錯誤請丟 EngineError；逾時丟 EngineTimeout。
訊息裡不要放使用者的話或金鑰——它們可能被寫進伺服器日誌。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class STTEngine(Protocol):
    def transcribe(self, wav: bytes, *, timeout: float | None = None) -> str:
        """wav：16 kHz／16 bit／單聲道的完整 WAV 位元組。回傳辨識文字（沒聽到語音回空字串）。"""
        ...


@runtime_checkable
class LLMEngine(Protocol):
    def complete(self, system_prompt: str, user_text: str, *,
                 timeout: float | None = None) -> str:
        """單輪問答（不帶歷史）：回傳回答文字。"""
        ...


@runtime_checkable
class TTSEngine(Protocol):
    def synthesize(self, text: str, *, timeout: float | None = None) -> bytes:
        """回傳完整 WAV 位元組：PCM16 單聲道，取樣率須在 wavio.PLAYABLE_RATES 內（SERVER_API §3.2）。

        不在清單內的取樣率會被伺服器擋下（502 upstream_failed），不會送給裝置。
        """
        ...


@dataclass(frozen=True)
class Engines:
    stt: STTEngine
    llm: LLMEngine
    tts: TTSEngine
