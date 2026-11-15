# SPDX-License-Identifier: MIT
"""設定檔載入與驗證（JSON）。

規則：
- 以底線開頭的鍵（例如 "_說明"）會被忽略，可當註解用。
- 不認得的鍵直接報錯（打錯字比靜默用預設值安全）。
- 相對路徑以「設定檔所在資料夾」為準；沒給設定檔時以目前工作目錄為準。
- 金鑰不放設定檔：外部引擎只填「環境變數名稱」（api_key_env）。
- 錯誤訊息只寫鍵名與原因，不回顯設定值。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .errors import ConfigError
from . import SAMPLE_RATE

ENGINE_KINDS = ("fake", "openai_compat", "custom")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


# ---------- 小工具 ----------

def _visible(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if not str(k).startswith("_")}


def _section(raw: Mapping[str, Any], key: str, where: str = "") -> dict[str, Any]:
    v = raw.get(key, {})
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ConfigError("%s%s: expected an object" % (where, key))
    return _visible(v)


def check_keys(d: Mapping[str, Any], allowed: tuple[str, ...], where: str) -> None:
    extra = sorted(k for k in d if k not in allowed)
    if extra:
        hint = ""
        if any(("key" in k.lower() or "token" in k.lower() or "secret" in k.lower())
               for k in extra):
            hint = "（金鑰不能放設定檔，請用 api_key_env 指向環境變數名稱）"
        raise ConfigError("%s: unknown key(s) %s%s" % (where, ", ".join(extra), hint))


def read(d: Mapping[str, Any], key: str, default: Any, types: tuple[type, ...], where: str,
         *, lo: float | None = None, hi: float | None = None,
         choices: tuple[Any, ...] | None = None, none_ok: bool = False) -> Any:
    """讀一個欄位並檢查型別與範圍；布林不會被當成整數。"""
    if key not in d:
        return default
    v = d[key]
    if v is None and none_ok:
        return None
    if isinstance(v, bool) and bool not in types:
        raise ConfigError("%s.%s: unexpected boolean" % (where, key))
    if not isinstance(v, types):
        raise ConfigError("%s.%s: expected %s" % (where, key, "/".join(t.__name__ for t in types)))
    if lo is not None and v < lo:
        raise ConfigError("%s.%s: must be >= %s" % (where, key, lo))
    if hi is not None and v > hi:
        raise ConfigError("%s.%s: must be <= %s" % (where, key, hi))
    if choices is not None and v not in choices:
        raise ConfigError("%s.%s: must be one of %s" % (where, key, ", ".join(map(str, choices))))
    return v


def parse_hhmm(value: str, where: str) -> int:
    """'07:00' → 當天第幾分鐘（0–1439）。"""
    m = _HHMM_RE.match(value) if isinstance(value, str) else None
    if not m:
        raise ConfigError("%s: expected HH:MM (24h)" % where)
    return int(m.group(1)) * 60 + int(m.group(2))


def validate_base_url(url: Any, where: str) -> str:
    """外部引擎網址：只收 http／https、要有主機名、不可內嵌帳密。"""
    if not isinstance(url, str) or not url.strip():
        raise ConfigError("%s.base_url: required" % where)
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("%s.base_url: must be an http(s) URL" % where)
    if parts.username or parts.password:
        raise ConfigError("%s.base_url: do not embed credentials in the URL" % where)
    return url.strip().rstrip("/")


def validate_env_name(name: Any, where: str) -> str:
    """api_key_env 必須是環境變數「名稱」；貼了金鑰本身會因為格式不符而被擋下。"""
    if not isinstance(name, str) or not _ENV_NAME_RE.match(name):
        raise ConfigError("%s.api_key_env: must be an environment variable NAME "
                          "(letters, digits, underscore)" % where)
    return name


# ---------- 設定資料結構 ----------

@dataclass(frozen=True)
class ServerCfg:
    host: str = "127.0.0.1"
    port: int = 8787
    base_path: str = ""            # 反向代理沒去掉前綴時用，例如 "/ask-api"
    request_timeout_s: float = 30.0  # 單次 socket 讀取逾時
    hard_timeout_s: float = 15.0     # STT→LLM→TTS 總硬上限（SERVER_API §4）
    max_concurrent: int = 4          # 同時處理中的問答數，超過回 503


@dataclass(frozen=True)
class LimitsCfg:
    max_seconds: float = 15
    max_body_bytes: int | None = None  # None＝依 max_seconds 推算（44 B 標頭＋PCM）

    @property
    def body_cap(self) -> int:
        if self.max_body_bytes is not None:
            return self.max_body_bytes
        return 44 + int(self.max_seconds * SAMPLE_RATE) * 2


@dataclass(frozen=True)
class AuthCfg:
    token_sha256: tuple[str, ...] = ()
    health_requires_token: bool = True


@dataclass(frozen=True)
class EngineChoice:
    kind: str = "fake"
    params: Mapping[str, Any] = field(default_factory=dict)  # 只含被選中那一塊的設定


@dataclass(frozen=True)
class ChildModeCfg:
    rules_file: str | None = None   # None＝找 child_rules.json，沒有就用 child_rules.example.json
    empty_stt: str = "speak"        # speak＝200＋「沒聽清楚」語音；error＝422 no_speech
    max_answer_chars: int = 150


@dataclass(frozen=True)
class QuotaCfg:
    per_minute: int = 6              # 0＝不限
    per_day: int = 200               # 0＝不限
    utc_offset_minutes: int = 480    # 每日額度與使用時段用的時區（預設 UTC+8）
    hours_enabled: bool = False
    hours_start: int = 7 * 60
    hours_end: int = 20 * 60 + 30


@dataclass(frozen=True)
class QALogCfg:
    enabled: bool = True
    path: str = "./data/qa_log.jsonl"
    retention_days: int = 30


@dataclass(frozen=True)
class DisplayCfg:
    font_path: str = ""   # 空字串＝不產生 X-Display-Bitmap
    font_index: int = 0
    font_size: int = 16


@dataclass(frozen=True)
class Config:
    server: ServerCfg = ServerCfg()
    limits: LimitsCfg = LimitsCfg()
    auth: AuthCfg = AuthCfg()
    stt: EngineChoice = EngineChoice()
    llm: EngineChoice = EngineChoice()
    tts: EngineChoice = EngineChoice()
    child_mode: ChildModeCfg = ChildModeCfg()
    quota: QuotaCfg = QuotaCfg()
    qa_log: QALogCfg = QALogCfg()
    display: DisplayCfg = DisplayCfg()
    base_dir: Path = Path(".")

    def resolve(self, p: str) -> Path:
        """相對路徑以設定檔所在資料夾為準。"""
        path = Path(os.path.expanduser(p))
        return path if path.is_absolute() else (self.base_dir / path)


# ---------- 載入 ----------

def _parse_server(raw: dict) -> ServerCfg:
    check_keys(raw, ("host", "port", "base_path", "request_timeout_s", "hard_timeout_s",
                     "max_concurrent"), "server")
    d = ServerCfg()
    base_path = read(raw, "base_path", d.base_path, (str,), "server")
    if base_path and (not base_path.startswith("/") or base_path.endswith("/")
                      or " " in base_path):
        raise ConfigError("server.base_path: must look like /ask-api (leading slash, no trailing slash)")
    host = read(raw, "host", d.host, (str,), "server")
    if not host:
        raise ConfigError("server.host: must not be empty")
    return ServerCfg(
        host=host,
        port=read(raw, "port", d.port, (int,), "server", lo=0, hi=65535),
        base_path=base_path,
        request_timeout_s=float(read(raw, "request_timeout_s", d.request_timeout_s,
                                     (int, float), "server", lo=1)),
        hard_timeout_s=float(read(raw, "hard_timeout_s", d.hard_timeout_s,
                                  (int, float), "server", lo=1)),
        max_concurrent=read(raw, "max_concurrent", d.max_concurrent, (int,), "server", lo=1),
    )


def _parse_limits(raw: dict) -> LimitsCfg:
    check_keys(raw, ("max_seconds", "max_body_bytes"), "limits")
    d = LimitsCfg()
    max_seconds = read(raw, "max_seconds", d.max_seconds, (int, float), "limits", lo=1, hi=120)
    if float(max_seconds).is_integer():
        max_seconds = int(max_seconds)
    return LimitsCfg(
        max_seconds=max_seconds,
        max_body_bytes=read(raw, "max_body_bytes", None, (int,), "limits", lo=1000, none_ok=True),
    )


def _parse_auth(raw: dict) -> AuthCfg:
    check_keys(raw, ("token_sha256", "health_requires_token"), "auth")
    hashes = read(raw, "token_sha256", [], (list,), "auth")
    out = []
    for i, h in enumerate(hashes):
        h = h.strip().lower() if isinstance(h, str) else ""
        if not _HASH_RE.match(h):
            # 不回顯內容：萬一有人把明文 token 貼在這裡，錯誤訊息不能洩漏它
            raise ConfigError("auth.token_sha256[%d]: must be a 64-char hex SHA-256 "
                              "(use: python3 -m mod_ask_server.hash_token)" % i)
        out.append(h)
    return AuthCfg(
        token_sha256=tuple(out),
        health_requires_token=read(raw, "health_requires_token", True, (bool,), "auth"),
    )


def _parse_engine(raw: dict, name: str) -> EngineChoice:
    check_keys(raw, ("type",) + ENGINE_KINDS, name)
    kind = read(raw, "type", "fake", (str,), name, choices=ENGINE_KINDS)
    block = raw.get(kind, {})
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ConfigError("%s.%s: expected an object" % (name, kind))
    return EngineChoice(kind=kind, params=_visible(block))


def _parse_child_mode(raw: dict) -> ChildModeCfg:
    check_keys(raw, ("rules_file", "empty_stt", "max_answer_chars"), "child_mode")
    d = ChildModeCfg()
    return ChildModeCfg(
        rules_file=read(raw, "rules_file", None, (str,), "child_mode", none_ok=True),
        empty_stt=read(raw, "empty_stt", d.empty_stt, (str,), "child_mode",
                       choices=("speak", "error")),
        max_answer_chars=read(raw, "max_answer_chars", d.max_answer_chars, (int,),
                              "child_mode", lo=10, hi=500),
    )


def _parse_quota(raw: dict) -> QuotaCfg:
    check_keys(raw, ("per_minute", "per_day", "utc_offset_minutes", "allowed_hours"), "quota")
    d = QuotaCfg()
    hours = _section(raw, "allowed_hours", "quota.")
    check_keys(hours, ("enabled", "start", "end"), "quota.allowed_hours")
    enabled = read(hours, "enabled", False, (bool,), "quota.allowed_hours")
    start = parse_hhmm(hours.get("start", "07:00"), "quota.allowed_hours.start")
    end = parse_hhmm(hours.get("end", "20:30"), "quota.allowed_hours.end")
    if enabled and start == end:
        raise ConfigError("quota.allowed_hours: start and end must differ")
    return QuotaCfg(
        per_minute=read(raw, "per_minute", d.per_minute, (int,), "quota", lo=0),
        per_day=read(raw, "per_day", d.per_day, (int,), "quota", lo=0),
        utc_offset_minutes=read(raw, "utc_offset_minutes", d.utc_offset_minutes, (int,),
                                "quota", lo=-720, hi=840),
        hours_enabled=enabled, hours_start=start, hours_end=end,
    )


def _parse_qa_log(raw: dict) -> QALogCfg:
    check_keys(raw, ("enabled", "path", "retention_days"), "qa_log")
    d = QALogCfg()
    path = read(raw, "path", d.path, (str,), "qa_log")
    if not path:
        raise ConfigError("qa_log.path: must not be empty (set enabled=false to turn logging off)")
    return QALogCfg(
        enabled=read(raw, "enabled", d.enabled, (bool,), "qa_log"),
        path=path,
        retention_days=read(raw, "retention_days", d.retention_days, (int,), "qa_log",
                            lo=1, hi=3650),
    )


def _parse_display(raw: dict) -> DisplayCfg:
    check_keys(raw, ("font_path", "font_index", "font_size"), "display")
    d = DisplayCfg()
    return DisplayCfg(
        font_path=read(raw, "font_path", d.font_path, (str,), "display"),
        font_index=read(raw, "font_index", d.font_index, (int,), "display", lo=0),
        font_size=read(raw, "font_size", d.font_size, (int,), "display", lo=6, hi=32),
    )


_TOP_KEYS = ("server", "limits", "auth", "stt", "llm", "tts", "child_mode", "quota",
             "qa_log", "display")


def config_from_dict(raw: Mapping[str, Any], base_dir: Path | str = ".") -> Config:
    """從已解析的 dict 建立 Config（測試與 load_config 共用）。"""
    if not isinstance(raw, dict):
        raise ConfigError("config: top level must be an object")
    raw = _visible(raw)
    check_keys(raw, _TOP_KEYS, "config")
    return Config(
        server=_parse_server(_section(raw, "server")),
        limits=_parse_limits(_section(raw, "limits")),
        auth=_parse_auth(_section(raw, "auth")),
        stt=_parse_engine(_section(raw, "stt"), "stt"),
        llm=_parse_engine(_section(raw, "llm"), "llm"),
        tts=_parse_engine(_section(raw, "tts"), "tts"),
        child_mode=_parse_child_mode(_section(raw, "child_mode")),
        quota=_parse_quota(_section(raw, "quota")),
        qa_log=_parse_qa_log(_section(raw, "qa_log")),
        display=_parse_display(_section(raw, "display")),
        base_dir=Path(base_dir),
    )


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """讀設定檔；path 為 None 時全用預設值（假引擎、只綁本機）。"""
    if path is None:
        return Config(base_dir=Path.cwd())
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError("cannot read config file: %s" % e.strerror) from e
    try:
        raw = json.loads(text)
    except ValueError as e:
        raise ConfigError("config file is not valid JSON: %s" % e) from e
    return config_from_dict(raw, base_dir=p.resolve().parent)
