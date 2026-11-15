# SPDX-License-Identifier: MIT
"""測試共用工具：產生 WAV、在隨機埠起真的伺服器、假的外部引擎伺服器。"""
from __future__ import annotations

import copy
import http.client
import io
import json
import math
import struct
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import logging  # noqa: E402

# 測試時不要讓伺服器的警告訊息洗版（需要檢查時用 assertLogs，它不受影響）
logging.getLogger("mod_ask").addHandler(logging.NullHandler())

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from mod_ask_server.app import create_server  # noqa: E402
from mod_ask_server.child_mode import ChildRules  # noqa: E402
from mod_ask_server.config import config_from_dict  # noqa: E402

DEVICE_ID = "0123456789abcdef"
EXAMPLE_RULES = SERVER_DIR / "child_rules.example.json"


def make_wav(seconds: float = 2.0, rate: int = 16000, channels: int = 1, width: int = 2,
             amp: int = 6000, silent: bool = False) -> bytes:
    """用標準函式庫 wave 產生測試 WAV（刻意不用 mod_ask_server.wavio，避免用被測物測自己）。"""
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = 0 if silent else int(amp * math.sin(2 * math.pi * 220 * i / rate))
            if width == 2:
                frames += struct.pack("<h", v) * channels
            else:
                frames += bytes([(v >> 8) + 128 & 0xFF]) * channels
        w.writeframes(bytes(frames))
    return buf.getvalue()


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Resp:
    def __init__(self, status: int, headers, body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        return json.loads(self.body.decode("utf-8"))


class ServerHandle:
    def __init__(self, server, tmpdir: tempfile.TemporaryDirectory) -> None:
        self.server = server
        self.port = server.port
        self.tmpdir = tmpdir
        self.log_path = Path(tmpdir.name) / "qa_log.jsonl"
        self.thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                                       daemon=True)
        self.thread.start()
        if not server.started.wait(5):
            raise RuntimeError("server did not start")

    def close(self) -> None:
        self.server.stop()          # shutdown + server_close：釋放埠
        self.thread.join(timeout=5)
        self.tmpdir.cleanup()

    def conn(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None) -> Resp:
        c = self.conn()
        try:
            c.request(method, path, body=body, headers=headers or {})
            r = c.getresponse()
            return Resp(r.status, r.headers, r.read())
        finally:
            c.close()

    def ask(self, wav: bytes | None = None, headers: dict | None = None,
            path: str = "/v1/ask") -> Resp:
        h = {"Content-Type": "audio/wav", "Accept": "audio/wav", "X-Device-Id": DEVICE_ID,
             "X-Fw-Version": "0.1.0"}
        h.update(headers or {})
        return self.request("POST", path, make_wav() if wav is None else wav, h)

    def log_lines(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(x) for x in self.log_path.read_text(encoding="utf-8").splitlines()]


def start_server(test, config: dict | None = None, *, engines=None, rules=None, clock=None,
                 environ=None, display=None, prepare=None) -> ServerHandle:
    """起一個綁在 127.0.0.1 隨機埠的伺服器；測試結束時自動關閉。

    config 會疊在預設設定上（埠 0、紀錄檔放暫存資料夾、使用範例規則檔）。
    prepare(tmpdir_path) 可在啟動前先在暫存資料夾放檔案（例如舊的紀錄）。
    """
    tmp = tempfile.TemporaryDirectory(prefix="modask-test-")
    base = {"server": {"port": 0}, "qa_log": {"path": str(Path(tmp.name) / "qa_log.jsonl")}}
    cfg = config_from_dict(deep_merge(base, config or {}), base_dir=tmp.name)
    if prepare:
        prepare(Path(tmp.name))
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    if display is not None:
        kwargs["display"] = display
    server = create_server(cfg, engines=engines,
                           rules=rules or ChildRules.from_file(EXAMPLE_RULES),
                           environ=environ if environ is not None else {}, **kwargs)
    handle = ServerHandle(server, tmp)
    test.addCleanup(handle.close)
    return handle


# ---------- 假的「OpenAI 相容」上游伺服器 ----------

class StubUpstream:
    """記錄收到的請求，並依路徑回預先設定的內容。

    responses: {路徑: (狀態碼, Content-Type, bytes, 延遲秒數)}；也可加 extra_headers。
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses: dict[str, tuple] = {}
        self.extra_headers: dict[str, dict] = {}
        stub = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # 安靜
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(n)
                stub.requests.append({"path": self.path, "headers": dict(self.headers.items()),
                                      "body": body})
                status, ctype, data, delay = stub.responses.get(
                    self.path, (404, "text/plain", b"not found", 0))
                if delay:
                    threading.Event().wait(delay)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    for k, v in stub.extra_headers.get(self.path, {}).items():
                        self.send_header(k, v)
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass
                self.close_connection = True

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return "http://127.0.0.1:%d/v1" % self.port

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_stub(test) -> StubUpstream:
    stub = StubUpstream()
    test.addCleanup(stub.close)
    return stub


def free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port
