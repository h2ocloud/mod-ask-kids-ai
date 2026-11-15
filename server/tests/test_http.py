# SPDX-License-Identifier: MIT
"""HTTP 端到端：真的在 127.0.0.1 隨機埠起伺服器，用 http.client／raw socket 打。

涵蓋 SERVER_API 的 health、ask 成功、各種錯誤碼（400／401／404／405／411／413／415／429／
502／503／504）、空 STT、兒童過濾、個資遮蔽、X-Answer-Text、X-Display-Bitmap、TTS 取樣率、
提問紀錄、以及串接「OpenAI 相容」外部引擎（本機假上游）。測試結束時伺服器一定會被關掉。
"""
import base64
import http.client
import io
import json
import re
import socket
import struct
import threading
import time
import unittest
import wave
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote_to_bytes

import _helpers
from _helpers import DEVICE_ID, make_wav, start_server, start_stub
from mod_ask_server import display
from mod_ask_server.auth import hash_token
from mod_ask_server.child_mode import DEFAULT_SAFE_REPLIES, DEFAULT_SYSTEM_PROMPT
from mod_ask_server.engines import Engines, FakeLLM, FakeSTT, FakeTTS
from mod_ask_server.errors import EngineError, EngineTimeout
from mod_ask_server.qa_log import format_ts
from mod_ask_server.wavio import PLAYABLE_RATES, build_wav, parse_wav

TZ8 = timezone(timedelta(hours=8))
PHONE = "0912-345-678"


def answer_text(resp) -> str:
    return unquote_to_bytes(resp.headers["X-Answer-Text"]).decode("utf-8")


def engines(stt=None, llm=None, tts=None) -> Engines:
    return Engines(stt=stt or FakeSTT(), llm=llm or FakeLLM(), tts=tts or FakeTTS())


class CountingLLM:
    def __init__(self, reply="天空是藍色的。"):
        self.reply, self.calls = reply, []

    def complete(self, system_prompt, user_text, *, timeout=None):
        self.calls.append((system_prompt, user_text))
        return self.reply


class RaisingLLM:
    def __init__(self, exc):
        self.exc = exc

    def complete(self, system_prompt, user_text, *, timeout=None):
        raise self.exc


class SlowLLM:
    def complete(self, system_prompt, user_text, *, timeout=None):
        time.sleep(1.3)
        return "太慢了。"


class FixedTTS:
    def __init__(self, wav: bytes):
        self.wav = wav

    def synthesize(self, text, *, timeout=None):
        return self.wav


def tone_wav(rate: int, channels: int = 1, bits: int = 16) -> bytes:
    return build_wav(bytes(int(rate * 0.3) * channels * bits // 8), rate, channels, bits)


def assert_error(test, resp, status, code):
    test.assertEqual(resp.status, status, resp.body[:200])
    test.assertEqual(resp.headers["Content-Type"], "application/json")
    body = resp.json()
    test.assertEqual(set(body), {"error"})
    test.assertEqual(body["error"]["code"], code)
    test.assertIsInstance(body["error"]["message"], str)
    test.assertTrue(re.fullmatch(r"[0-9a-f]{16}", resp.headers["X-Request-Id"]))
    return body["error"]


# ---------------------------------------------------------------- health

class HealthTests(unittest.TestCase):
    def test_health_matches_spec(self):
        h = start_server(self)
        r = h.request("GET", "/v1/health", headers={"X-Device-Id": DEVICE_ID, "X-Fw-Version": "0.1.0"})
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "application/json")
        self.assertEqual(r.json(), {"ok": True, "api": "mod-ask/1", "max_seconds": 15,
                                    "sample_rate": 16000})
        self.assertTrue(r.json()["api"].startswith("mod-ask/1"))
        self.assertIsInstance(r.json()["max_seconds"], int)

    def test_health_reflects_configured_max_seconds(self):
        h = start_server(self, {"limits": {"max_seconds": 8}})
        self.assertEqual(h.request("GET", "/v1/health").json()["max_seconds"], 8)

    def test_query_string_is_ignored_and_other_paths_404(self):
        h = start_server(self)
        self.assertEqual(h.request("GET", "/v1/health?x=1").status, 200)
        for path in ("/", "/health", "/v1", "/v1/health/", "/v2/health", "/v1/ask/extra"):
            assert_error(self, h.request("GET", path), 404, "not_found")

    def test_wrong_method_is_405_with_allow(self):
        h = start_server(self)
        r = h.request("POST", "/v1/health", b"")
        assert_error(self, r, 405, "method_not_allowed")
        self.assertEqual(r.headers["Allow"], "GET")
        r = h.request("GET", "/v1/ask")
        assert_error(self, r, 405, "method_not_allowed")
        self.assertEqual(r.headers["Allow"], "POST")
        for m in ("PUT", "DELETE", "PATCH", "OPTIONS"):
            self.assertEqual(h.request(m, "/v1/ask").status, 405, m)
        self.assertEqual(h.request("HEAD", "/v1/ask").status, 405)

    def test_base_path_prefix(self):
        h = start_server(self, {"server": {"base_path": "/ask-api"}})
        self.assertEqual(h.request("GET", "/ask-api/v1/health").status, 200)
        self.assertEqual(h.ask(path="/ask-api/v1/ask").status, 200)
        assert_error(self, h.request("GET", "/v1/health"), 404, "not_found")
        assert_error(self, h.request("GET", "/ask-apix/v1/health"), 404, "not_found")

    def test_binds_to_loopback_by_default(self):
        h = start_server(self)
        self.assertEqual(h.server.server_address[0], "127.0.0.1")

    def test_response_never_leaks_python_version(self):
        h = start_server(self)
        r = h.request("GET", "/v1/health")
        self.assertEqual(r.headers["Server"], "mod-ask")


# ---------------------------------------------------------------- ask 成功

class AskSuccessTests(unittest.TestCase):
    def test_success_response_matches_spec(self):
        h = start_server(self)
        r = h.ask()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "audio/wav")
        self.assertEqual(int(r.headers["Content-Length"]), len(r.body))
        self.assertIsNone(r.headers.get("Transfer-Encoding"))
        self.assertRegex(r.headers["X-Request-Id"], r"^[0-9a-f]{16}$")
        text = answer_text(r)
        self.assertIn("你問的是：", text)
        self.assertIn("這是測試伺服器的假回答。", text)
        self.assertLessEqual(len(unquote_to_bytes(r.headers["X-Answer-Text"])), 200)
        self.assertNotIn("X-Display-Bitmap", r.headers)     # 沒設字型就不送
        with wave.open(io.BytesIO(r.body)) as w:                # 標準函式庫確認是可播的 WAV
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()),
                             (1, 2, 16000))
            self.assertGreater(w.getnframes(), 8000)

    def test_request_ids_are_unique(self):
        h = start_server(self)
        ids = {h.ask().headers["X-Request-Id"] for _ in range(5)}
        self.assertEqual(len(ids), 5)

    def test_max_length_upload_is_accepted(self):
        h = start_server(self)
        wav = make_wav(15.0)
        self.assertEqual(len(wav), 480044)
        self.assertEqual(h.ask(wav).status, 200)

    def test_exact_minimum_length_is_accepted(self):
        self.assertEqual(start_server(self).ask(make_wav(0.3)).status, 200)

    def test_content_type_parameters_and_case_are_tolerated(self):
        h = start_server(self)
        self.assertEqual(h.ask(headers={"Content-Type": "AUDIO/WAV"}).status, 200)
        self.assertEqual(h.ask(headers={"Content-Type": "audio/wav; charset=binary"}).status, 200)

    def test_missing_optional_headers_still_work(self):
        h = start_server(self)
        r = h.request("POST", "/v1/ask", make_wav(), {"Content-Type": "audio/wav"})
        self.assertEqual(r.status, 200)  # 沒有 X-Device-Id／Accept／X-Fw-Version

    def test_answer_header_is_truncated_on_char_boundary_but_audio_is_complete(self):
        long_answer = "這是一個很長的回答，" * 12 + "結束。"   # 約 110 字、超過 200 B
        h = start_server(self, engines=engines(llm=CountingLLM(long_answer)))
        r = h.ask()
        raw = unquote_to_bytes(r.headers["X-Answer-Text"])
        self.assertLessEqual(len(raw), 200)
        self.assertGreater(len(raw), 190)
        self.assertTrue(long_answer.startswith(raw.decode("utf-8")))  # 合法 UTF-8、是前綴
        self.assertGreater(parse_wav(r.body).duration, 5)               # 語音仍是完整回答

    def test_long_llm_answer_is_clipped_to_three_sentences(self):
        h = start_server(self, engines=engines(llm=CountingLLM("一。二。三。四。五。")))
        self.assertEqual(answer_text(h.ask()), "一。二。三。")

    def test_device_id_handling_in_log(self):
        h = start_server(self)
        h.ask(headers={"X-Device-Id": "0123456789ABCDEF"})
        h.ask(headers={"X-Device-Id": "not-hex"})
        h.ask(headers={"X-Device-Id": "x" * 500})
        r = h.request("POST", "/v1/ask", make_wav(), {"Content-Type": "audio/wav"})
        self.assertEqual(r.status, 200)
        self.assertEqual([e["device_id"] for e in h.log_lines()],
                         ["0123456789abcdef", "unknown", "unknown", "unknown"])


# ---------------------------------------------------------------- 輸入驗證

class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.h = start_server(self)

    def test_415_wrong_content_type(self):
        for ctype in ("text/plain", "audio/x-wav", "audio/mpeg", "application/octet-stream", ""):
            headers = {"Content-Type": ctype} if ctype else {}
            c = self.h.conn()
            c.putrequest("POST", "/v1/ask")
            for k, v in headers.items():
                c.putheader(k, v)
            c.putheader("Content-Length", "4")
            c.endheaders(b"RIFF")
            r = c.getresponse()
            body = json.loads(r.read())
            c.close()
            self.assertEqual((r.status, body["error"]["code"]), (415, "unsupported_media_type"), ctype)

    def test_411_missing_content_length(self):
        c = self.h.conn()
        c.putrequest("POST", "/v1/ask")
        c.putheader("Content-Type", "audio/wav")
        c.putheader("X-Device-Id", DEVICE_ID)
        c.endheaders()  # 沒有本文也沒有 Content-Length
        r = c.getresponse()
        body = json.loads(r.read())
        c.close()
        self.assertEqual((r.status, body["error"]["code"]), (411, "length_required"))
        self.assertIn("Content-Length", body["error"]["message"])

    def test_411_chunked_upload_not_supported(self):
        c = self.h.conn()
        c.request("POST", "/v1/ask", body=iter([make_wav(1)[:2000]]), encode_chunked=True,
                  headers={"Content-Type": "audio/wav", "Transfer-Encoding": "chunked"})
        r = c.getresponse()
        self.assertEqual(r.status, 411)
        self.assertEqual(json.loads(r.read())["error"]["code"], "length_required")
        c.close()

    def test_400_invalid_content_length(self):
        for value in ("abc", "-5", "1e3", "12 34", ""):
            c = self.h.conn()
            c.putrequest("POST", "/v1/ask")
            c.putheader("Content-Type", "audio/wav")
            c.putheader("Content-Length", value)
            c.endheaders()
            r = c.getresponse()
            self.assertIn(r.status, (400, 411), value)
            r.read()
            c.close()

    def test_413_too_long_by_bytes(self):
        r = self.h.ask(make_wav(16))   # 512,044 B > 480,044 B
        err = assert_error(self, r, 413, "too_long")
        self.assertEqual(err["message"], "audio longer than 15 s")
        r = self.h.ask(make_wav(40))
        assert_error(self, r, 413, "too_long")

    def test_413_huge_content_length_is_rejected_without_waiting_for_body(self):
        c = self.h.conn()
        c.putrequest("POST", "/v1/ask")
        c.putheader("Content-Type", "audio/wav")
        c.putheader("Content-Length", "1000000000")
        c.endheaders()  # 一個位元組的本文都不送：伺服器不能傻等
        t0 = time.time()
        r = c.getresponse()
        self.assertEqual(r.status, 413)
        self.assertEqual(json.loads(r.read())["error"]["code"], "too_long")
        self.assertLess(time.time() - t0, 5)
        c.close()

    def test_413_too_long_by_duration(self):
        h = start_server(self, {"limits": {"max_seconds": 1, "max_body_bytes": 1000000}})
        assert_error(self, h.ask(make_wav(2.0)), 413, "too_long")
        self.assertEqual(h.ask(make_wav(1.0)).status, 200)

    def test_400_bad_audio(self):
        for body in (b"", b"not a wav at all", b"\xff\xfb" * 5000, make_wav(1)[:30],
                     make_wav(1, rate=8000), make_wav(1, rate=44100), make_wav(1, channels=2),
                     make_wav(1, width=1)):
            assert_error(self, self.h.ask(body), 400, "bad_audio")

    def test_400_bad_audio_for_truncated_upload_body(self):
        # 標頭說 100000 B 但只送了 20 B 就關閉寫入端
        s = socket.create_connection(("127.0.0.1", self.h.port), timeout=10)
        s.sendall(b"POST /v1/ask HTTP/1.1\r\nHost: x\r\nContent-Type: audio/wav\r\n"
                  b"Content-Length: 100000\r\n\r\n" + make_wav(1)[:20])
        s.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := s.recv(4096):
            data += chunk
        s.close()
        head, _, body = data.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 400"), head[:40])
        self.assertEqual(json.loads(body)["error"]["code"], "bad_audio")

    def test_400_too_short(self):
        for secs in (0.0, 0.1, 0.29):
            assert_error(self, self.h.ask(make_wav(secs)), 400, "too_short")

    def test_errors_do_not_poison_the_server(self):
        self.h.ask(b"junk")
        self.h.ask(make_wav(16))
        self.assertEqual(self.h.ask().status, 200)

    def raw_exchange(self, request: bytes) -> tuple[bytes, dict]:
        s = socket.create_connection(("127.0.0.1", self.h.port), timeout=10)
        s.sendall(request)
        data = b""
        while chunk := s.recv(4096):
            data += chunk
        s.close()
        head, _, body = data.partition(b"\r\n\r\n")
        return head, json.loads(body)

    def test_protocol_level_errors_from_http_server_are_also_json(self):
        head, body = self.raw_exchange(b"GET /v1/health HTTP/9.9\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 505"), head[:30])
        self.assertIn(b"application/json", head)
        self.assertEqual(body["error"]["code"], "http_version_not_supported")
        head, body = self.raw_exchange(b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 414"), head[:30])
        self.assertEqual(body["error"]["code"], "uri_too_long")
        head, body = self.raw_exchange(b"GARBAGE\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 400"), head[:30])
        self.assertEqual(body["error"]["code"], "bad_request")


# ---------------------------------------------------------------- 授權

class AuthTests(unittest.TestCase):
    def setUp(self):
        import secrets
        self.tok = "dev-" + secrets.token_hex(12)
        self.h = start_server(self, {"auth": {"token_sha256": [hash_token(self.tok)]}})

    def bearer(self, t):
        return {"Authorization": "Bearer " + t}

    def test_401_without_or_with_wrong_token(self):
        for headers in ({}, self.bearer("wrong"), self.bearer(""), {"Authorization": self.tok},
                        {"Authorization": "Basic " + self.tok},
                        self.bearer(self.tok + "x")):
            r = self.h.ask(headers=headers)
            assert_error(self, r, 401, "unauthorized")
            self.assertIn("Bearer", r.headers["WWW-Authenticate"])

    def test_correct_token_is_accepted(self):
        self.assertEqual(self.h.ask(headers=self.bearer(self.tok)).status, 200)

    def test_token_is_checked_before_reading_a_large_body(self):
        r = self.h.ask(make_wav(15), headers={})   # 480 KB 上傳，沒帶 token
        assert_error(self, r, 401, "unauthorized")

    def test_health_requires_token_by_default_when_enabled(self):
        assert_error(self, self.h.request("GET", "/v1/health"), 401, "unauthorized")
        r = self.h.request("GET", "/v1/health", headers=self.bearer(self.tok))
        self.assertEqual(r.status, 200)

    def test_health_can_be_left_open(self):
        h = start_server(self, {"auth": {"token_sha256": [hash_token(self.tok)],
                                         "health_requires_token": False}})
        self.assertEqual(h.request("GET", "/v1/health").status, 200)
        assert_error(self, h.ask(), 401, "unauthorized")

    def test_no_hashes_means_no_check(self):
        h = start_server(self)
        self.assertEqual(h.ask(headers={"Authorization": "Bearer anything"}).status, 200)
        self.assertEqual(h.ask().status, 200)

    def test_unauthorized_requests_are_not_logged_or_counted(self):
        h = start_server(self, {"auth": {"token_sha256": [hash_token(self.tok)]},
                                "quota": {"per_minute": 1}})
        for _ in range(3):
            self.assertEqual(h.ask().status, 401)
        self.assertEqual(h.ask(headers=self.bearer(self.tok)).status, 200)  # 額度沒被未授權的請求吃掉
        self.assertEqual(len(h.log_lines()), 1)


# ---------------------------------------------------------------- 額度與時段

class QuotaE2ETests(unittest.TestCase):
    def setUp(self):
        self.now = [datetime(2026, 11, 15, 12, 0, tzinfo=TZ8).timestamp()]

    def clock(self):
        return self.now[0]

    def test_per_minute_429_with_retry_after_then_recovers(self):
        h = start_server(self, {"quota": {"per_minute": 2, "per_day": 0}}, clock=self.clock)
        self.assertEqual(h.ask().status, 200)
        self.now[0] += 5
        self.assertEqual(h.ask().status, 200)
        self.now[0] += 5
        r = h.ask()
        err = assert_error(self, r, 429, "rate_limited")
        self.assertIn("minute", err["message"])
        retry = int(r.headers["Retry-After"])
        self.assertEqual(retry, 50)
        self.assertEqual(len(h.log_lines()), 2)          # 被擋的不會進紀錄
        self.now[0] += retry
        self.assertEqual(h.ask().status, 200)

    def test_per_device_not_global(self):
        h = start_server(self, {"quota": {"per_minute": 1, "per_day": 0}}, clock=self.clock)
        self.assertEqual(h.ask(headers={"X-Device-Id": "a" * 16}).status, 200)
        self.assertEqual(h.ask(headers={"X-Device-Id": "b" * 16}).status, 200)
        assert_error(self, h.ask(headers={"X-Device-Id": "a" * 16}), 429, "rate_limited")

    def test_daily_limit(self):
        h = start_server(self, {"quota": {"per_minute": 0, "per_day": 2}}, clock=self.clock)
        for _ in range(2):
            self.assertEqual(h.ask().status, 200)
            self.now[0] += 3600
        r = h.ask()
        assert_error(self, r, 429, "rate_limited")
        self.assertEqual(int(r.headers["Retry-After"]), 10 * 3600)  # 現在 14:00，到當地午夜 10 小時
        self.now[0] += 10 * 3600
        self.assertEqual(h.ask().status, 200)                        # 隔天重新計

    def test_allowed_hours(self):
        cfg = {"quota": {"allowed_hours": {"enabled": True, "start": "07:00", "end": "20:30"}}}
        h = start_server(self, cfg, clock=self.clock)
        self.assertEqual(h.ask().status, 200)                        # 12:00
        self.now[0] = datetime(2026, 11, 15, 22, 0, tzinfo=TZ8).timestamp()
        r = h.ask()
        assert_error(self, r, 429, "rate_limited")
        self.assertEqual(int(r.headers["Retry-After"]), 9 * 3600)    # 到隔天 07:00
        # 時段外：不管內容對不對都是 429，而且大上傳也不會卡住
        assert_error(self, h.ask(b"junk"), 429, "rate_limited")
        assert_error(self, h.ask(make_wav(15)), 429, "rate_limited")
        self.now[0] = datetime(2026, 11, 16, 7, 0, tzinfo=TZ8).timestamp()
        self.assertEqual(h.ask().status, 200)

    def test_health_is_not_rate_limited(self):
        h = start_server(self, {"quota": {"per_minute": 1, "per_day": 1,
                                          "allowed_hours": {"enabled": True, "start": "01:00",
                                                            "end": "02:00"}}}, clock=self.clock)
        for _ in range(5):
            self.assertEqual(h.request("GET", "/v1/health").status, 200)

    def test_invalid_audio_does_not_consume_quota(self):
        h = start_server(self, {"quota": {"per_minute": 1, "per_day": 0}}, clock=self.clock)
        for _ in range(3):
            self.assertEqual(h.ask(b"junk").status, 400)
        self.assertEqual(h.ask().status, 200)


# ---------------------------------------------------------------- 空 STT／兒童模式

class EmptySttTests(unittest.TestCase):
    def test_empty_recognition_returns_200_with_spoken_prompt(self):
        h = start_server(self, {"stt": {"fake": {"fixed_text": ""}}})
        r = h.ask()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers["Content-Type"], "audio/wav")
        self.assertEqual(answer_text(r), "我沒聽清楚，再說一次好嗎？")
        self.assertGreater(parse_wav(r.body).frames, 0)                   # 有語音

    def test_llm_is_not_called_and_log_is_empty_question(self):
        llm = CountingLLM()
        h = start_server(self, engines=engines(stt=FakeSTT(""), llm=llm))
        r = h.ask()
        self.assertEqual(answer_text(r), "我沒聽清楚，再說一次好嗎？")
        self.assertEqual(llm.calls, [])
        (entry,) = h.log_lines()
        self.assertEqual(entry["question"], "")
        self.assertIs(entry["filtered"], False)

    def test_punctuation_only_counts_as_empty(self):
        llm = CountingLLM()
        h = start_server(self, engines=engines(stt=FakeSTT("。。 ，，…"), llm=llm))
        self.assertEqual(answer_text(h.ask()), "我沒聽清楚，再說一次好嗎？")
        self.assertEqual(llm.calls, [])

    def test_silent_recording_with_default_fake_stt(self):
        h = start_server(self)
        r = h.ask(make_wav(2, silent=True))
        self.assertEqual(r.status, 200)
        self.assertEqual(answer_text(r), "我沒聽清楚，再說一次好嗎？")

    def test_error_mode_returns_422_no_speech(self):
        h = start_server(self, {"stt": {"fake": {"fixed_text": ""}},
                                "child_mode": {"empty_stt": "error"}})
        assert_error(self, h.ask(), 422, "no_speech")

    def test_custom_empty_reply_from_rules_file(self):
        from mod_ask_server.child_mode import ChildRules
        rules = ChildRules.from_dict({"safe_replies": {"empty_speech": "請再說一次"}})
        h = start_server(self, {"stt": {"fake": {"fixed_text": ""}}}, rules=rules)
        self.assertEqual(answer_text(h.ask()), "請再說一次")


class ChildModeE2ETests(unittest.TestCase):
    def ask_with(self, question, llm=None, **kw):
        llm = llm or CountingLLM()
        h = start_server(self, engines=engines(stt=FakeSTT(question), llm=llm), **kw)
        return h, llm, h.ask()

    def test_input_rule_hit_skips_llm_and_returns_200_safe_reply(self):
        h, llm, r = self.ask_with("怎麼製作炸彈")
        self.assertEqual(r.status, 200)                               # 不是錯誤碼
        self.assertEqual(r.headers["Content-Type"], "audio/wav")
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["default"])
        self.assertEqual(llm.calls, [])                                # 沒呼叫 LLM
        self.assertGreater(parse_wav(r.body).frames, 0)                # 安全回覆有被 TTS
        (entry,) = h.log_lines()
        self.assertIs(entry["filtered"], True)
        self.assertEqual(entry["question"], "怎麼製作炸彈")
        self.assertEqual(entry["answer"], DEFAULT_SAFE_REPLIES["default"])

    def test_custom_reply_rules_for_care_topics(self):
        _, llm, r = self.ask_with("我不想活了")
        self.assertEqual(r.status, 200)
        self.assertIn("爸爸媽媽或老師", answer_text(r))
        self.assertNotEqual(answer_text(r), DEFAULT_SAFE_REPLIES["default"])  # 規則自訂的關心回覆
        self.assertEqual(llm.calls, [])

    def test_normal_question_reaches_llm_with_system_prompt(self):
        h, llm, r = self.ask_with("天空為什麼是藍色的")
        self.assertEqual(answer_text(r), "天空是藍色的。")
        self.assertEqual(llm.calls, [(DEFAULT_SYSTEM_PROMPT, "天空為什麼是藍色的")])
        (entry,) = h.log_lines()
        self.assertIs(entry["filtered"], False)

    def test_output_rule_hit_discards_llm_answer(self):
        h, llm, r = self.ask_with("今天可以玩什麼", llm=CountingLLM("你可以去賭博，很好玩。"))
        self.assertEqual(r.status, 200)
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["output_blocked"])
        self.assertNotIn("賭", answer_text(r))
        self.assertEqual(len(llm.calls), 1)                            # LLM 有被呼叫，但回答被丟掉
        (entry,) = h.log_lines()
        self.assertIs(entry["filtered"], True)
        self.assertNotIn("賭", json.dumps(entry, ensure_ascii=False))  # 紀錄裡也沒有被丟掉的回答

    def test_llm_asking_for_personal_info_is_replaced(self):
        _, _, r = self.ask_with("你好", llm=CountingLLM("你好呀！你叫什麼名字呢？"))
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["output_blocked"])

    def test_empty_llm_answer_gets_fallback(self):
        _, _, r = self.ask_with("你好", llm=CountingLLM("  \n "))
        self.assertEqual(r.status, 200)
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["no_answer"])

    def test_pii_in_question_skips_llm_and_is_masked_in_log(self):
        h, llm, r = self.ask_with("我的電話是" + PHONE + "你可以打給我")
        self.assertEqual(r.status, 200)
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["pii"])
        self.assertEqual(llm.calls, [])                                # 個資不會送到 LLM
        (entry,) = h.log_lines()
        self.assertIs(entry["filtered"], True)
        self.assertIn("[電話]", entry["question"])
        raw_log = h.log_path.read_text(encoding="utf-8")
        self.assertNotIn("0912", raw_log)
        self.assertNotIn("345-678", raw_log)

    def test_email_and_address_are_masked_in_log(self):
        at = chr(64)
        for q, token in (("寄信給 kid" + at + "mail.example 好嗎", "mail.example"),
                         ("我住台北市大安區和平東路二段100號", "和平東路")):
            h, llm, r = self.ask_with(q)
            self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["pii"])
            self.assertEqual(llm.calls, [])
            self.assertNotIn(token, h.log_path.read_text(encoding="utf-8"))

    def test_pii_echoed_by_llm_is_masked_in_log_answer(self):
        h, _, r = self.ask_with("你好", llm=CountingLLM("你可以打 02-2345-6789 問問看。"))
        (entry,) = h.log_lines()
        self.assertNotIn("2345", entry["answer"])
        self.assertIn("[電話]", entry["answer"])

    def test_rules_file_is_loaded_from_config_path(self):
        import tempfile
        from pathlib import Path
        from mod_ask_server.app import create_server
        from mod_ask_server.config import config_from_dict
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "rules.json").write_text(json.dumps(
                {"input_rules": [{"id": "x", "keywords": ["恐龍"], "reply": "不聊恐龍"}]}),
                encoding="utf-8")
            cfg = config_from_dict({"server": {"port": 0}, "qa_log": {"enabled": False},
                                    "child_mode": {"rules_file": "rules.json"}}, base_dir=d)
            srv = create_server(cfg, engines=engines(stt=FakeSTT("恐龍好大")))
            self.addCleanup(srv.server_close)
            self.assertEqual(srv.service.rules.screen_input("恐龍好大").reply, "不聊恐龍")
            self.assertFalse(srv.service.rules.screen_input("炸彈").blocked)  # 沒載入範例規則


# ---------------------------------------------------------------- 引擎失敗與逾時

class EngineFailureTests(unittest.TestCase):
    def test_upstream_failed_502(self):
        class BadSTT:
            def transcribe(self, wav, *, timeout=None):
                raise EngineError("boom")

        for eng in (engines(stt=BadSTT()), engines(llm=RaisingLLM(EngineError("boom")))):
            h = start_server(self, engines=eng)
            err = assert_error(self, h.ask(), 502, "upstream_failed")
            self.assertNotIn("boom", err["message"])

    def test_unexpected_engine_exception_is_502_not_500(self):
        h = start_server(self, engines=engines(llm=RaisingLLM(RuntimeError("secret detail"))))
        err = assert_error(self, h.ask(), 502, "upstream_failed")
        self.assertNotIn("secret", err["message"])
        self.assertEqual(h.ask(headers={"X-Device-Id": "b" * 16}).status, 502)  # 伺服器還活著

    def test_upstream_timeout_504(self):
        h = start_server(self, engines=engines(llm=RaisingLLM(EngineTimeout("slow"))))
        assert_error(self, h.ask(), 504, "upstream_timeout")

    def test_hard_timeout_returns_504(self):
        h = start_server(self, {"server": {"hard_timeout_s": 1}}, engines=engines(llm=SlowLLM()))
        t0 = time.time()
        assert_error(self, h.ask(), 504, "upstream_timeout")
        self.assertLess(time.time() - t0, 5)

    def test_engines_receive_the_remaining_time_as_timeout(self):
        seen = []

        class SpyLLM:
            def complete(self, system_prompt, user_text, *, timeout=None):
                seen.append(timeout)
                return "好。"
        h = start_server(self, {"server": {"hard_timeout_s": 12}}, engines=engines(llm=SpyLLM()))
        self.assertEqual(h.ask().status, 200)
        self.assertTrue(0 < seen[0] <= 12)

    def test_tts_returning_garbage_is_502(self):
        for bad in (b"", b"not audio", b"RIFF\0\0\0\0WAVE", tone_wav(16000)[:20]):
            h = start_server(self, engines=engines(tts=FixedTTS(bad)))
            assert_error(self, h.ask(), 502, "upstream_failed")

    def test_tts_with_zero_frames_is_502(self):
        h = start_server(self, engines=engines(tts=FixedTTS(build_wav(b"", 16000))))
        assert_error(self, h.ask(), 502, "upstream_failed")

    def test_tts_non_mono_or_non_16bit_is_502(self):
        for wav in (tone_wav(16000, channels=2), tone_wav(16000, bits=8), tone_wav(16000, bits=24)):
            h = start_server(self, engines=engines(tts=FixedTTS(wav)))
            assert_error(self, h.ask(), 502, "upstream_failed")

    def test_tts_playable_sample_rates_are_passed_through_unchanged(self):
        # SERVER_API §3.2：功放只吃 8000／16000／32000／44100／48000；
        # 裝置會把 24000、22050（×2）與 12000、11025（×4）升頻後播放。伺服器不必重取樣。
        for rate in sorted(PLAYABLE_RATES):
            h = start_server(self, engines=engines(tts=FixedTTS(tone_wav(rate))))
            r = h.ask()
            self.assertEqual(r.status, 200, rate)
            out = parse_wav(r.body)
            self.assertEqual((out.sample_rate, out.channels, out.bits), (rate, 1, 16))

    def test_tts_unsupported_sample_rate_is_502_not_sent_to_device(self):
        for rate in (7999, 9600, 10000, 18000, 22000, 37800, 47999, 64000, 96000):
            h = start_server(self, engines=engines(tts=FixedTTS(tone_wav(rate))))
            r = h.ask()
            err = assert_error(self, r, 502, "upstream_failed")
            self.assertNotEqual(r.headers["Content-Type"], "audio/wav", rate)
            self.assertIn("tts", err["message"])

    def test_tts_wav_is_normalized_to_a_canonical_header(self):
        # 上游用 0xFFFFFFFF 當串流長度、還夾了 LIST chunk：回給裝置的是長度正確的標準檔
        pcm = bytes(range(200)) * 10
        odd = (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVE"
               + b"LIST" + struct.pack("<I", 4) + b"INFO"
               + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
               + b"data" + struct.pack("<I", 0xFFFFFFFF) + pcm)
        h = start_server(self, engines=engines(tts=FixedTTS(odd)))
        r = h.ask()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, build_wav(pcm, 24000))
        with wave.open(io.BytesIO(r.body)) as w:
            self.assertEqual(w.getnframes(), len(pcm) // 2)

    def test_failures_do_not_write_log_entries(self):
        h = start_server(self, engines=engines(llm=RaisingLLM(EngineError("x"))))
        h.ask()
        self.assertEqual(h.log_lines(), [])


class ConcurrencyTests(unittest.TestCase):
    def test_busy_server_returns_503_with_retry_after(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingSTT:
            def transcribe(self, wav, *, timeout=None):
                entered.set()
                release.wait(15)
                return "你好"
        h = start_server(self, {"server": {"max_concurrent": 1}},
                         engines=engines(stt=BlockingSTT()))
        self.addCleanup(release.set)
        result = {}
        t = threading.Thread(target=lambda: result.update(r=h.ask()))
        t.start()
        self.assertTrue(entered.wait(10))
        r = h.ask(headers={"X-Device-Id": "b" * 16})
        assert_error(self, r, 503, "unavailable")
        self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)
        release.set()
        t.join(10)
        self.assertEqual(result["r"].status, 200)
        self.assertEqual(h.ask().status, 200)          # 恢復後正常（slot 有被釋放）


# ---------------------------------------------------------------- 紀錄

class QaLogE2ETests(unittest.TestCase):
    def test_log_entry_fields_and_no_audio(self):
        h = start_server(self)
        wav = make_wav(2.0)
        self.assertEqual(h.ask(wav).status, 200)
        raw = h.log_path.read_bytes()
        (entry,) = [json.loads(x) for x in raw.splitlines()]
        self.assertEqual(set(entry), {"ts", "device_id", "question", "answer", "filtered",
                                      "latency_ms"})
        self.assertRegex(entry["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(entry["device_id"], DEVICE_ID)
        self.assertEqual(entry["question"], "（測試）你好，今天天氣好嗎")
        self.assertIn("假回答", entry["answer"])
        self.assertIs(entry["filtered"], False)
        self.assertIsInstance(entry["latency_ms"], int)
        self.assertGreaterEqual(entry["latency_ms"], 0)
        self.assertLess(len(raw), 2000)                         # 只有文字，沒有錄音
        self.assertNotIn(base64.b64encode(wav[44:200]), raw)
        # 暫存資料夾裡也沒有別的檔案（沒有錄音檔）
        names = {p.name for p in h.log_path.parent.iterdir()}
        self.assertEqual(names, {"qa_log.jsonl"})

    def test_logging_can_be_disabled(self):
        h = start_server(self, {"qa_log": {"enabled": False}})
        self.assertEqual(h.ask().status, 200)
        self.assertFalse(h.log_path.exists())

    def test_expired_entries_are_purged_at_startup(self):
        now = time.time()

        def prepare(tmp):
            def line(ts, q):
                return json.dumps({"ts": format_ts(ts), "device_id": DEVICE_ID, "question": q,
                                   "answer": "a", "filtered": False, "latency_ms": 1},
                                  ensure_ascii=False) + "\n"
            (tmp / "qa_log.jsonl").write_text(
                line(now - 45 * 86400, "old") + line(now - 29 * 86400, "recent"),
                encoding="utf-8")
        h = start_server(self, {"qa_log": {"retention_days": 30}}, prepare=prepare)
        self.assertEqual([e["question"] for e in h.log_lines()], ["recent"])

    def test_retention_days_comes_from_config(self):
        now = time.time()

        def prepare(tmp):
            (tmp / "qa_log.jsonl").write_text(json.dumps(
                {"ts": format_ts(now - 3 * 86400), "device_id": "d", "question": "q",
                 "answer": "a", "filtered": False, "latency_ms": 1}) + "\n", encoding="utf-8")
        h = start_server(self, {"qa_log": {"retention_days": 2}}, prepare=prepare)
        self.assertEqual(h.log_lines(), [])


# ---------------------------------------------------------------- X-Display-Bitmap

class DisplayE2ETests(unittest.TestCase):
    def test_no_bitmap_header_without_font_config(self):
        h = start_server(self)
        self.assertNotIn("X-Display-Bitmap", h.ask().headers)

    def test_unusable_font_config_does_not_break_requests(self):
        h = start_server(self, {"display": {"font_path": "no-such-font.ttf"}})
        r = h.ask()
        self.assertEqual(r.status, 200)
        self.assertNotIn("X-Display-Bitmap", r.headers)

    @unittest.skipUnless(display.pillow_available(), "需要 Pillow（選用相依）")
    def test_bitmap_header_when_renderer_available(self):
        from PIL import ImageFont
        try:
            font = ImageFont.load_default(size=14)
        except TypeError:
            self.skipTest("Pillow 太舊")
        h = start_server(self, engines=engines(llm=CountingLLM("Hello kid")),
                         display=display.DisplayRenderer(font, 14))
        r = h.ask()
        self.assertEqual(r.status, 200)
        value = r.headers["X-Display-Bitmap"]
        self.assertEqual(len(value), 684)
        raw = base64.b64decode(value, validate=True)
        self.assertEqual(len(raw), 512)
        self.assertGreater(sum(bin(b).count("1") for b in raw), 20)

    def test_bitmap_header_uses_injected_renderer_without_pillow(self):
        class FakeRenderer:
            def render(self, text):
                rows = [[0] * 128 for _ in range(32)]
                rows[0][0] = 1
                return display.bitmap_header_value(rows)
        h = start_server(self, display=FakeRenderer())
        r = h.ask()
        raw = base64.b64decode(r.headers["X-Display-Bitmap"], validate=True)
        self.assertEqual((len(raw), raw[0]), (512, 0x80))


# ---------------------------------------------------------------- 串接 OpenAI 相容外部引擎

KEY = "test-" + "key-" + "y" * 12


class OpenAICompatPipelineTests(unittest.TestCase):
    ANSWER = "因為陽光被空氣散開了。藍色最容易被散開喔。"

    def setUp(self):
        self.stub = start_stub(self)
        self.pcm = struct.pack("<2400h", *[(i % 80) * 40 for i in range(2400)])
        self.set_json("/v1/audio/transcriptions", {"text": "天空為什麼是藍色的"})
        self.set_json("/v1/chat/completions",
                      {"choices": [{"message": {"content": self.ANSWER}}]})
        self.stub.responses["/v1/audio/speech"] = (200, "audio/pcm", self.pcm, 0)

    def set_json(self, path, obj, status=200, delay=0):
        self.stub.responses[path] = (status, "application/json", json.dumps(obj).encode(), delay)

    def config(self, **tts):
        base = {"base_url": self.stub.base, "use_env_proxy": False, "timeout_s": 5}
        t = dict(base, model="tts-m", response_format="pcm", sample_rate=24000)
        t.update(tts)
        return {"stt": {"type": "openai_compat", "openai_compat": dict(base, model="stt-m")},
                "llm": {"type": "openai_compat", "openai_compat": dict(base, model="llm-m")},
                "tts": {"type": "openai_compat", "openai_compat": t}}

    def calls(self, path):
        return [r for r in self.stub.requests if r["path"] == path]

    def test_full_roundtrip_with_pcm_tts(self):
        h = start_server(self, self.config(), environ={"ASK_LLM_API_KEY": KEY})
        wav = make_wav(1.0)
        r = h.ask(wav)
        self.assertEqual(r.status, 200)
        self.assertEqual(answer_text(r), self.ANSWER)
        out = parse_wav(r.body)
        self.assertEqual((out.sample_rate, out.channels, out.bits), (24000, 1, 16))  # 不重取樣
        self.assertEqual(out.pcm, self.pcm)

        (stt,) = self.calls("/v1/audio/transcriptions")
        self.assertIn(wav[44:100], stt["body"])                      # 錄音有上傳給 STT
        (llm,) = self.calls("/v1/chat/completions")
        body = json.loads(llm["body"])
        self.assertEqual(body["messages"][0], {"role": "system", "content": DEFAULT_SYSTEM_PROMPT})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "天空為什麼是藍色的"})
        (tts,) = self.calls("/v1/audio/speech")
        self.assertEqual(json.loads(tts["body"])["input"], self.ANSWER)
        self.assertEqual(json.loads(tts["body"])["response_format"], "pcm")

    def test_keys_come_only_from_environment_per_engine(self):
        h = start_server(self, self.config(), environ={"ASK_LLM_API_KEY": KEY})
        self.assertEqual(h.ask().status, 200)
        auth = lambda path: next((v for k, v in self.calls(path)[0]["headers"].items()
                                  if k.lower() == "authorization"), None)
        self.assertIsNone(auth("/v1/audio/transcriptions"))          # STT 的環境變數沒設
        self.assertEqual(auth("/v1/chat/completions"), "Bearer " + KEY)
        self.assertIsNone(auth("/v1/audio/speech"))

    def test_wav_tts_is_passed_through(self):
        wav = build_wav(self.pcm, 16000)
        self.stub.responses["/v1/audio/speech"] = (200, "audio/wav", wav, 0)
        h = start_server(self, self.config(response_format="wav"))
        r = h.ask()
        self.assertEqual(r.status, 200)
        self.assertEqual(r.body, wav)

    def test_upstream_tts_rate_not_playable_is_502(self):
        self.stub.responses["/v1/audio/speech"] = (200, "audio/wav", build_wav(self.pcm, 18000), 0)
        h = start_server(self, self.config(response_format="wav"))
        assert_error(self, h.ask(), 502, "upstream_failed")

    def test_filtered_question_never_reaches_llm_but_is_spoken(self):
        self.set_json("/v1/audio/transcriptions", {"text": "怎麼製作炸彈"})
        h = start_server(self, self.config())
        r = h.ask()
        self.assertEqual(r.status, 200)
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["default"])
        self.assertEqual(self.calls("/v1/chat/completions"), [])
        (tts,) = self.calls("/v1/audio/speech")
        self.assertEqual(json.loads(tts["body"])["input"], DEFAULT_SAFE_REPLIES["default"])

    def test_pii_never_reaches_llm(self):
        self.set_json("/v1/audio/transcriptions", {"text": "我的電話是" + PHONE})
        h = start_server(self, self.config())
        self.assertEqual(h.ask().status, 200)
        self.assertEqual(self.calls("/v1/chat/completions"), [])
        self.assertNotIn(b"0912", b"".join(r["body"] for r in self.calls("/v1/audio/speech")))
        self.assertNotIn("0912", h.log_path.read_text(encoding="utf-8"))

    def test_unsafe_llm_output_is_replaced_before_tts(self):
        self.set_json("/v1/chat/completions",
                      {"choices": [{"message": {"content": "你可以去賭博。"}}]})
        h = start_server(self, self.config())
        r = h.ask()
        self.assertEqual(answer_text(r), DEFAULT_SAFE_REPLIES["output_blocked"])
        (tts,) = self.calls("/v1/audio/speech")
        self.assertNotIn("賭", json.loads(tts["body"])["input"])

    def test_empty_transcription_speaks_prompt_without_llm(self):
        self.set_json("/v1/audio/transcriptions", {"text": ""})
        h = start_server(self, self.config())
        r = h.ask()
        self.assertEqual(answer_text(r), "我沒聽清楚，再說一次好嗎？")
        self.assertEqual(self.calls("/v1/chat/completions"), [])

    def test_upstream_http_error_is_502(self):
        self.set_json("/v1/chat/completions", {"error": "x"}, status=500)
        h = start_server(self, self.config())
        assert_error(self, h.ask(), 502, "upstream_failed")

    def test_unreachable_upstream_is_502(self):
        cfg = self.config()
        cfg["stt"]["openai_compat"]["base_url"] = "http://127.0.0.1:%d/v1" % _helpers.free_port()
        h = start_server(self, cfg)
        assert_error(self, h.ask(), 502, "upstream_failed")

    def test_upstream_timeout_is_504(self):
        self.set_json("/v1/audio/transcriptions", {"text": "你好"}, delay=2.0)
        cfg = self.config()
        cfg["stt"]["openai_compat"]["timeout_s"] = 0.5
        h = start_server(self, cfg)
        assert_error(self, h.ask(), 504, "upstream_timeout")


if __name__ == "__main__":
    unittest.main()
