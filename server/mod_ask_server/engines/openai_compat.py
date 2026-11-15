# SPDX-License-Identifier: MIT
"""「OpenAI 相容 HTTP API」外部引擎（只用 urllib）。

- STT：POST {base}/audio/transcriptions（multipart/form-data：file、model…）→ JSON {"text": ...}
- LLM：POST {base}/chat/completions（JSON：model、messages…）→ choices[0].message.content
- TTS：POST {base}/audio/speech（JSON：model、input、voice、response_format）→ WAV 或 PCM

API key 只從環境變數讀（api_key_env 指定名稱；沒設定就不帶 Authorization，給不需要金鑰的本機服務用）。
安全：不跟隨重新導向（避免金鑰被帶去別的主機）、限制回應大小、錯誤訊息不含回應內容。
"""
from __future__ import annotations

import http.client
import json
import logging
import re
import secrets
import socket
import urllib.error
import urllib.request
from typing import Any, Mapping

from ..errors import EngineError, EngineTimeout
from ..wavio import build_wav

log = logging.getLogger("mod_ask.engines")

_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)

MAX_TEXT_RESPONSE = 1 << 20      # STT／LLM 的 JSON 回應上限：1 MiB
MAX_AUDIO_RESPONSE = 16 << 20    # TTS 回應上限：16 MiB


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        return None  # 回傳 None → urllib 丟 HTTPError(3xx)，我們當成失敗


class HttpClient:
    """極簡 POST 客戶端：帶可選的 Bearer 金鑰、逾時、大小上限。"""

    def __init__(self, base_url: str, api_key: str | None, *, name: str,
                 use_env_proxy: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key or None
        self.name = name
        handlers: list[Any] = [_NoRedirect()]
        if not use_env_proxy:
            handlers.append(urllib.request.ProxyHandler({}))
        self._opener = urllib.request.build_opener(*handlers)

    def post(self, path: str, body: bytes, content_type: str, *, timeout: float | None,
             max_response: int) -> bytes:
        req = urllib.request.Request(self.base_url + path, data=body, method="POST")
        req.add_header("Content-Type", content_type)
        req.add_header("Accept", "*/*")
        req.add_header("User-Agent", "mod-ask-server")
        if self._api_key:
            req.add_header("Authorization", "Bearer " + self._api_key)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                data = resp.read(max_response + 1)
        except urllib.error.HTTPError as e:
            code = e.code
            e.close()
            raise EngineError("%s upstream returned HTTP %d" % (self.name, code)) from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, (socket.timeout, TimeoutError)):
                raise EngineTimeout("%s upstream timed out" % self.name) from None
            raise EngineError("%s upstream connection failed" % self.name) from None
        except (socket.timeout, TimeoutError):
            raise EngineTimeout("%s upstream timed out" % self.name) from None
        except (http.client.HTTPException, OSError):
            raise EngineError("%s upstream connection failed" % self.name) from None
        if len(data) > max_response:
            raise EngineError("%s upstream response too large" % self.name)
        return data


def _api_key(env: Mapping[str, str], env_name: str, name: str) -> str | None:
    key = env.get(env_name, "").strip()
    if not key:
        log.warning("%s: environment variable %s is not set; requests will carry no "
                    "Authorization header", name, env_name)
        return None
    return key


def encode_multipart(fields: Mapping[str, str], file_field: str, filename: str,
                     file_bytes: bytes, file_type: str) -> tuple[bytes, str]:
    """組 multipart/form-data 本文。回傳 (body, Content-Type 標頭值)。"""
    boundary = "modask" + secrets.token_hex(16)
    parts: list[bytes] = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, k, v)).encode("utf-8"))
    parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                  'Content-Type: %s\r\n\r\n' % (boundary, file_field, filename, file_type)
                  ).encode("utf-8"))
    parts.append(file_bytes)
    parts.append(("\r\n--%s--\r\n" % boundary).encode("ascii"))
    return b"".join(parts), "multipart/form-data; boundary=" + boundary


def _timeout(configured: float, requested: float | None) -> float:
    return configured if requested is None else max(0.1, min(configured, requested))


def _json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise EngineError("%s upstream returned invalid JSON" % name) from None


class OpenAICompatSTT:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 language: str = "", timeout_s: float = 10.0,
                 extra_fields: Mapping[str, Any] | None = None,
                 use_env_proxy: bool = True) -> None:
        self.model = model
        self.language = language
        self.timeout_s = timeout_s
        self.extra_fields = dict(extra_fields or {})
        self._http = HttpClient(base_url, api_key, name="stt", use_env_proxy=use_env_proxy)

    def transcribe(self, wav: bytes, *, timeout: float | None = None) -> str:
        fields = {"model": self.model, "response_format": "json"}
        if self.language:
            fields["language"] = self.language
        fields.update({k: str(v) for k, v in self.extra_fields.items()})
        body, ctype = encode_multipart(fields, "file", "audio.wav", wav, "audio/wav")
        data = self._http.post("/audio/transcriptions", body, ctype,
                               timeout=_timeout(self.timeout_s, timeout),
                               max_response=MAX_TEXT_RESPONSE)
        obj = _json(data, "stt")
        text = obj.get("text") if isinstance(obj, dict) else None
        if not isinstance(text, str):
            raise EngineError("stt upstream response has no text field")
        return text.strip()


class OpenAICompatLLM:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 timeout_s: float = 10.0, max_tokens: int = 200, temperature: float = 0.7,
                 extra_body: Mapping[str, Any] | None = None,
                 use_env_proxy: bool = True) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = dict(extra_body or {})
        self._http = HttpClient(base_url, api_key, name="llm", use_env_proxy=use_env_proxy)

    def complete(self, system_prompt: str, user_text: str, *,
                 timeout: float | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        payload.update(self.extra_body)
        data = self._http.post("/chat/completions",
                               json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               "application/json",
                               timeout=_timeout(self.timeout_s, timeout),
                               max_response=MAX_TEXT_RESPONSE)
        obj = _json(data, "llm")
        try:
            content = obj["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise EngineError("llm upstream response has no message content") from None
        if isinstance(content, list):  # 部分服務回「內容片段」陣列
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        if not isinstance(content, str):
            raise EngineError("llm upstream response has no message content")
        return _THINK_RE.sub("", content).strip()  # 不要把推理過程唸給小朋友聽


class OpenAICompatTTS:
    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 voice: str = "default", response_format: str = "wav",
                 sample_rate: int = 24000, timeout_s: float = 10.0,
                 extra_body: Mapping[str, Any] | None = None,
                 use_env_proxy: bool = True) -> None:
        if response_format not in ("wav", "pcm"):
            raise ValueError("response_format must be wav or pcm")
        self.model = model
        self.voice = voice
        self.response_format = response_format
        self.sample_rate = sample_rate  # 只有 pcm 需要：PCM 本身沒有取樣率資訊
        self.timeout_s = timeout_s
        self.extra_body = dict(extra_body or {})
        self._http = HttpClient(base_url, api_key, name="tts", use_env_proxy=use_env_proxy)

    def synthesize(self, text: str, *, timeout: float | None = None) -> bytes:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": self.response_format,
        }
        payload.update(self.extra_body)
        data = self._http.post("/audio/speech",
                               json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               "application/json",
                               timeout=_timeout(self.timeout_s, timeout),
                               max_response=MAX_AUDIO_RESPONSE)
        if not data:
            raise EngineError("tts upstream returned no audio")
        if self.response_format == "pcm":
            return build_wav(data[: len(data) // 2 * 2], self.sample_rate)
        return data  # wav：格式與標頭交給 service 統一檢查、正規化
