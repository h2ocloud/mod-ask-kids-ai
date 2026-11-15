# SPDX-License-Identifier: MIT
"""引擎介面與工廠：依設定檔建立 STT／LLM／TTS。

type 可以是：
- "fake"          假引擎（預設，不連網）
- "openai_compat" OpenAI 相容 HTTP API（base_url、model 寫設定檔，金鑰只讀環境變數）
- "custom"        自己的實作：{"factory": "my_module:make_engine"}，工廠收到該區塊的 dict
"""
from __future__ import annotations

import importlib
import os
from typing import Any, Callable, Mapping

from ..config import (Config, EngineChoice, check_keys, read, validate_base_url,
                      validate_env_name)
from ..errors import ConfigError
from ..wavio import PLAYABLE_RATES
from .base import Engines, LLMEngine, STTEngine, TTSEngine
from .fake import FakeLLM, FakeSTT, FakeTTS
from .openai_compat import OpenAICompatLLM, OpenAICompatSTT, OpenAICompatTTS, _api_key

__all__ = ["Engines", "STTEngine", "LLMEngine", "TTSEngine", "build_engines",
           "FakeSTT", "FakeLLM", "FakeTTS", "OpenAICompatSTT", "OpenAICompatLLM",
           "OpenAICompatTTS"]

_NUM = (int, float)


def _model(p: Mapping[str, Any], where: str) -> str:
    model = read(p, "model", "", (str,), where)
    if not model.strip():
        raise ConfigError("%s.model: required" % where)
    return model.strip()


def _dict(p: Mapping[str, Any], key: str, where: str) -> dict:
    v = read(p, key, {}, (dict,), where)
    return dict(v)


def _build_stt(choice: EngineChoice, env: Mapping[str, str]) -> STTEngine:
    p = choice.params
    if choice.kind == "fake":
        check_keys(p, ("fixed_text",), "stt.fake")
        return FakeSTT(read(p, "fixed_text", None, (str,), "stt.fake", none_ok=True))
    if choice.kind == "openai_compat":
        w = "stt.openai_compat"
        check_keys(p, ("base_url", "model", "api_key_env", "language", "timeout_s",
                       "extra_fields", "use_env_proxy"), w)
        return OpenAICompatSTT(
            validate_base_url(p.get("base_url"), w), _model(p, w),
            api_key=_api_key(env, validate_env_name(p.get("api_key_env", "ASK_STT_API_KEY"), w), "stt"),
            language=read(p, "language", "", (str,), w),
            timeout_s=float(read(p, "timeout_s", 10, _NUM, w, lo=0.5)),
            extra_fields=_dict(p, "extra_fields", w),
            use_env_proxy=read(p, "use_env_proxy", True, (bool,), w))
    return _custom(choice, "stt", STTEngine)


def _build_llm(choice: EngineChoice, env: Mapping[str, str]) -> LLMEngine:
    p = choice.params
    if choice.kind == "fake":
        check_keys(p, (), "llm.fake")
        return FakeLLM()
    if choice.kind == "openai_compat":
        w = "llm.openai_compat"
        check_keys(p, ("base_url", "model", "api_key_env", "timeout_s", "max_tokens",
                       "temperature", "extra_body", "use_env_proxy"), w)
        return OpenAICompatLLM(
            validate_base_url(p.get("base_url"), w), _model(p, w),
            api_key=_api_key(env, validate_env_name(p.get("api_key_env", "ASK_LLM_API_KEY"), w), "llm"),
            timeout_s=float(read(p, "timeout_s", 10, _NUM, w, lo=0.5)),
            max_tokens=read(p, "max_tokens", 200, (int,), w, lo=1, hi=4096),
            temperature=float(read(p, "temperature", 0.7, _NUM, w, lo=0, hi=2)),
            extra_body=_dict(p, "extra_body", w),
            use_env_proxy=read(p, "use_env_proxy", True, (bool,), w))
    return _custom(choice, "llm", LLMEngine)


def _build_tts(choice: EngineChoice, env: Mapping[str, str]) -> TTSEngine:
    p = choice.params
    if choice.kind == "fake":
        check_keys(p, (), "tts.fake")
        return FakeTTS()
    if choice.kind == "openai_compat":
        w = "tts.openai_compat"
        check_keys(p, ("base_url", "model", "api_key_env", "voice", "response_format",
                       "sample_rate", "timeout_s", "extra_body", "use_env_proxy"), w)
        return OpenAICompatTTS(
            validate_base_url(p.get("base_url"), w), _model(p, w),
            api_key=_api_key(env, validate_env_name(p.get("api_key_env", "ASK_TTS_API_KEY"), w), "tts"),
            voice=read(p, "voice", "default", (str,), w),
            response_format=read(p, "response_format", "wav", (str,), w,
                                 choices=("wav", "pcm")),
            # 只有 response_format=pcm 會用到：PCM 沒有取樣率資訊，要標成上游實際輸出的值。
            # 必須是裝置可播的取樣率（常見 TTS 的 24000 可以，不必重取樣）
            sample_rate=read(p, "sample_rate", 24000, (int,), w,
                             choices=tuple(sorted(PLAYABLE_RATES))),
            timeout_s=float(read(p, "timeout_s", 10, _NUM, w, lo=0.5)),
            extra_body=_dict(p, "extra_body", w),
            use_env_proxy=read(p, "use_env_proxy", True, (bool,), w))
    return _custom(choice, "tts", TTSEngine)


def _custom(choice: EngineChoice, name: str, protocol: type) -> Any:
    """載入 "module:callable" 工廠並呼叫（工廠由管理者在設定檔指定，視同可信程式碼）。"""
    w = "%s.custom" % name
    factory = read(choice.params, "factory", "", (str,), w)
    mod_name, sep, attr = factory.partition(":")
    if not (mod_name and sep and attr):
        raise ConfigError("%s.factory: expected 'module:callable'" % w)
    try:
        fn: Callable[..., Any] = getattr(importlib.import_module(mod_name), attr)
    except (ImportError, AttributeError) as e:
        raise ConfigError("%s.factory: cannot import %s:%s" % (w, mod_name, attr)) from e
    engine = fn(dict(choice.params))
    if not isinstance(engine, protocol):
        raise ConfigError("%s.factory: returned object does not implement %s"
                          % (w, protocol.__name__))
    return engine


def build_engines(cfg: Config, environ: Mapping[str, str] | None = None) -> Engines:
    """依設定建立三個引擎。environ 預設用 os.environ（金鑰只從這裡讀）。"""
    env = os.environ if environ is None else environ
    return Engines(stt=_build_stt(cfg.stt, env),
                   llm=_build_llm(cfg.llm, env),
                   tts=_build_tts(cfg.tts, env))
