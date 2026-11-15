# SPDX-License-Identifier: MIT
"""HTTP 層（標準函式庫 http.server）：兩個端點 GET /v1/health、POST /v1/ask。

請求驗證順序（先便宜、先不讀本文）：
  404／405 → 401 → 429（時段／額度預檢）→ 415 → 411／400／413（只看 Content-Length）
  → 讀本文 → 400／413／400（WAV 格式與長度）→ 429（正式計數）→ 503（太忙）→ 問答流程
所有錯誤都是 SERVER_API §3.3 的 JSON。回應一律 Connection: close（簡單、不佔執行緒）。
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import socket
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Mapping
from urllib.parse import urlsplit

from . import API_VERSION, SAMPLE_RATE
from .answer_text import encode_answer_text
from .auth import TokenAuth
from .child_mode import ChildRules, locate_rules_file
from .config import Config
from .display import DisplayRenderer, make_renderer
from .engines import Engines, build_engines
from .errors import ApiError
from .qa_log import QALog
from .quota import Quota
from .service import AskService
from .wavio import HTTP_STATUS, WavError, parse_wav, validate_upload

log = logging.getLogger("mod_ask.http")

_DEVICE_ID_RE = re.compile(r"^[0-9a-fA-F]{16}$")
_LENGTH_RE = re.compile(r"^[0-9]{1,12}$")
_DRAIN_LIMIT = 1 << 20   # 提早回錯誤時，最多先把 1 MiB 的上傳讀掉（免得裝置寫到一半被切線）
_CHUNK = 64 * 1024

# send_error（http.server 自己產生的錯誤，例如請求行太長）也回 JSON
_STDLIB_ERROR_CODES = {
    400: "bad_request", 404: "not_found", 405: "method_not_allowed", 408: "request_timeout",
    411: "length_required", 414: "uri_too_long", 431: "header_too_large",
    501: "not_implemented", 505: "http_version_not_supported",
}


class AskHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, cfg: Config, service: AskService, auth: TokenAuth, quota: Quota,
                 clock: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.service = service
        self.auth = auth
        self.quota = quota
        self.clock = clock
        self.slots = threading.BoundedSemaphore(cfg.server.max_concurrent)
        self.started = threading.Event()  # serve_forever 跑起來後會被設定
        if ":" in cfg.server.host:
            self.address_family = socket.AF_INET6
        super().__init__((cfg.server.host, cfg.server.port), _Handler)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self.service.qa_log.start_purge_thread()  # 啟動時清一次，之後每天清
        self.started.set()
        try:
            super().serve_forever(poll_interval)
        finally:
            self.started.clear()
            self.service.qa_log.stop()

    def stop(self) -> None:
        """停止服務並釋放埠（可在另一個執行緒呼叫；沒啟動過也安全）。"""
        if self.started.is_set():
            self.shutdown()
        self.server_close()
        self.service.qa_log.stop()

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionError, TimeoutError)):
            log.debug("client connection dropped: %s", type(exc).__name__)
        else:
            log.exception("unhandled error while handling a request")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mod-ask"
    sys_version = ""
    server: AskHTTPServer  # 型別提示

    # --- http.server 的雜項覆寫 ---
    def version_string(self) -> str:
        return self.server_version

    def setup(self) -> None:
        self.timeout = self.server.cfg.server.request_timeout_s
        super().setup()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        log.debug("%s", format % args)

    def log_request(self, code="-", size="-") -> None:  # 我們自己在 _dispatch 記一行
        pass

    def send_error(self, code, message=None, explain=None) -> None:  # noqa: ANN001
        status = int(code)
        name = _STDLIB_ERROR_CODES.get(status, "bad_request" if status < 500 else "internal")
        err = ApiError(status, name, (message or HTTPStatus(status).phrase).lower())
        if not getattr(self, "request_id", None):
            self.request_id = secrets.token_hex(8)
        if getattr(self, "request_version", "HTTP/0.9") == "HTTP/0.9":
            # 請求行壞掉時 http.server 還沒設定版本，會用沒有標頭的 0.9 格式回應；改成正常的回應
            self.request_version = "HTTP/1.1"
        self.close_connection = True
        self._send(status, "application/json", err.to_json_bytes(), {})

    # --- 路由 ---
    def do_GET(self) -> None: self._dispatch()
    def do_POST(self) -> None: self._dispatch()
    def do_HEAD(self) -> None: self._dispatch()
    def do_PUT(self) -> None: self._dispatch()
    def do_DELETE(self) -> None: self._dispatch()
    def do_PATCH(self) -> None: self._dispatch()
    def do_OPTIONS(self) -> None: self._dispatch()

    def _dispatch(self) -> None:
        t0 = time.monotonic()
        self.request_id = secrets.token_hex(8)
        self._status = 0
        self._pending = 0  # 還沒讀掉的請求本文位元組數
        self._unread = False  # 回錯誤時有沒有留下沒讀完的請求本文
        self.close_connection = True
        path = urlsplit(self.path).path
        try:
            route = self._route(path)
            if route == "/v1/health":
                self._require_method("GET")
                self._health()
            elif route == "/v1/ask":
                self._require_method("POST")
                self._ask()
            else:
                raise ApiError(404, "not_found", "no such endpoint")
        except ApiError as e:
            self._error(e)
            if self._unread:
                self._linger()
        except (ConnectionError, TimeoutError):
            pass  # 對方斷線或太慢：沒人可以回了
        except Exception:  # noqa: BLE001
            log.exception("unhandled error in request handler")
            self._error(ApiError(500, "internal", "internal error"))
        finally:
            log.info("%s %s -> %s (%d ms) rid=%s", self.command, path, self._status,
                     int((time.monotonic() - t0) * 1000), self.request_id)

    def _route(self, path: str) -> str:
        base = self.server.cfg.server.base_path
        if not base:
            return path
        if path == base or path.startswith(base + "/"):
            return path[len(base):] or "/"
        raise ApiError(404, "not_found", "no such endpoint")

    def _require_method(self, allowed: str) -> None:
        if self.command != allowed:
            raise ApiError(405, "method_not_allowed", "use %s" % allowed,
                           headers={"Allow": allowed})

    # --- 共用 ---
    def _check_auth(self) -> None:
        if not self.server.auth.verify(self.headers.get("Authorization")):
            raise ApiError(401, "unauthorized", "missing or invalid token",
                           headers={"WWW-Authenticate": 'Bearer realm="mod-ask"'})

    def _send(self, status: int, ctype: str, body: bytes, headers: Mapping[str, str]) -> None:
        self._status = status
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-Id", self.request_id)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, e: ApiError) -> None:
        self._discard_body()
        headers = dict(e.headers)
        if e.retry_after is not None:
            headers["Retry-After"] = str(int(e.retry_after))
        try:
            self._send(e.status, "application/json", e.to_json_bytes(), headers)
        except (ConnectionError, TimeoutError):
            pass

    def _discard_body(self) -> None:
        """提早回錯誤前，把（不太大的）上傳讀掉，免得對方還在送就被切線而看不到回應。"""
        n, self._pending = self._pending, 0
        if self.headers is not None and self.headers.get("Transfer-Encoding") is not None:
            self._unread = True  # 分塊上傳讀不出長度：回完錯誤後走 _linger
        if n > _DRAIN_LIMIT:
            self._unread = True  # 太大不讀了，同樣交給 _linger 收尾
        if not 0 < n <= _DRAIN_LIMIT:
            return
        try:
            while n > 0:
                chunk = self.rfile.read(min(n, _CHUNK))
                if not chunk:
                    return
                n -= len(chunk)
        except (OSError, ValueError):
            pass

    def _linger(self) -> None:
        """回完錯誤後的收尾：先關寫入端，再把對方還在送的資料讀掉一小段。

        直接 close 一個還有未讀資料的連線會送 RST，對方可能因此丟掉剛收到的錯誤回應。
        最多讀 1 MiB、每次最多等 0.5 秒；之後連線就關了。
        """
        try:
            self.connection.shutdown(socket.SHUT_WR)
            self.connection.settimeout(0.5)
            left = _DRAIN_LIMIT
            while left > 0:
                chunk = self.connection.recv(min(left, _CHUNK))
                if not chunk:
                    break
                left -= len(chunk)
        except OSError:
            pass

    def _read_body(self, n: int) -> bytes:
        parts, left = [], n
        while left > 0:
            chunk = self.rfile.read(min(left, _CHUNK))
            if not chunk:
                self._pending = 0
                raise ApiError(400, "bad_audio", "request body is shorter than Content-Length")
            parts.append(chunk)
            left -= len(chunk)
            self._pending = left
        return b"".join(parts)

    # --- GET /v1/health ---
    def _health(self) -> None:
        if self.server.cfg.auth.health_requires_token:
            self._check_auth()
        ms = self.server.cfg.limits.max_seconds
        body = json.dumps({"ok": True, "api": API_VERSION, "max_seconds": ms,
                           "sample_rate": SAMPLE_RATE}).encode("ascii")
        self._send(200, "application/json", body, {})

    # --- POST /v1/ask ---
    def _ask(self) -> None:
        started = time.monotonic()
        srv = self.server
        cfg = srv.cfg

        # 先把還沒讀的本文長度記起來，之後任何提早離開的錯誤都會先把它讀掉
        cl_raw = self.headers.get("Content-Length")
        if cl_raw is not None and _LENGTH_RE.match(cl_raw.strip()):
            self._pending = int(cl_raw.strip())

        self._check_auth()
        device_id = self._device_id()
        srv.quota.check(device_id, srv.clock())

        media = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if media != "audio/wav":
            raise ApiError(415, "unsupported_media_type", "Content-Type must be audio/wav")

        if self.headers.get("Transfer-Encoding") is not None or cl_raw is None:
            raise ApiError(411, "length_required",
                           "Content-Length is required (chunked upload is not supported)")
        if not _LENGTH_RE.match(cl_raw.strip()):
            raise ApiError(400, "bad_request", "invalid Content-Length")
        length = int(cl_raw.strip())
        if length > cfg.limits.body_cap:
            raise ApiError(413, "too_long", "audio longer than %g s" % cfg.limits.max_seconds)

        body = self._read_body(length)
        try:
            wav = parse_wav(body)
            validate_upload(wav, max_seconds=cfg.limits.max_seconds)
        except WavError as e:
            raise ApiError(HTTP_STATUS[e.code], e.code, str(e)) from None
        del body

        srv.quota.acquire(device_id, srv.clock())
        if not srv.slots.acquire(blocking=False):
            raise ApiError(503, "unavailable", "server is busy, try again later", retry_after=5)
        try:
            result = srv.service.handle(wav, device_id, started)
        finally:
            srv.slots.release()

        headers = {"X-Answer-Text": encode_answer_text(result.answer_text)}
        if result.display_bitmap:
            headers["X-Display-Bitmap"] = result.display_bitmap
        self._send(200, "audio/wav", result.wav, headers)

    def _device_id(self) -> str:
        """X-Device-Id 要是 16 位十六進位；缺少或格式不對一律歸到 "unknown"（共用一份額度）。"""
        raw = (self.headers.get("X-Device-Id") or "").strip()
        return raw.lower() if _DEVICE_ID_RE.match(raw) else "unknown"


# ---------- 組裝 ----------

def _is_loopback(host: str) -> bool:
    return host in ("localhost", "::1") or host.startswith("127.")


def create_server(cfg: Config, *, engines: Engines | None = None,
                  environ: Mapping[str, str] | None = None,
                  rules: ChildRules | None = None,
                  display: DisplayRenderer | None = None,
                  clock: Callable[[], float] = time.time) -> AskHTTPServer:
    """依設定組出伺服器（還沒開始服務；呼叫 serve_forever() 才會）。

    engines／rules／display／clock 可以注入（測試與自訂部署用）；沒給就依設定檔建立。
    """
    engines = engines or build_engines(cfg, environ)
    if rules is None:
        rules = ChildRules.from_file(locate_rules_file(cfg.child_mode.rules_file, cfg.base_dir))
    qa_log = QALog(cfg.resolve(cfg.qa_log.path), cfg.qa_log.retention_days,
                   cfg.qa_log.enabled, clock)
    service = AskService(cfg, engines, rules, qa_log,
                         display or make_renderer(cfg.display, cfg.resolve))
    server = AskHTTPServer(cfg, service, TokenAuth(cfg.auth.token_sha256), Quota(cfg.quota),
                           clock)
    if not _is_loopback(cfg.server.host):
        log.warning("listening on a non-loopback address; put this server behind an HTTPS "
                    "reverse proxy and do not expose plain HTTP directly")
        if not server.auth.enabled:
            log.warning("auth.token_sha256 is empty: anyone who can reach this port can use it")
    return server
