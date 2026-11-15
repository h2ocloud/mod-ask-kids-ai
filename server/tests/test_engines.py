# SPDX-License-Identifier: MIT
"""引擎：假引擎行為、OpenAI 相容外部引擎的請求格式（本機假 HTTP 伺服器＋unittest.mock）、
引擎設定驗證、自訂引擎工廠。這裡完全不會連到外部網路。"""
import email
import email.policy
import io
import json
import struct
import unittest
import urllib.error
import urllib.request
from unittest import mock

import _helpers
from _helpers import free_port, make_wav, start_stub
from mod_ask_server.config import config_from_dict
from mod_ask_server.engines import (FakeLLM, FakeSTT, FakeTTS, OpenAICompatLLM,
                                    OpenAICompatSTT, OpenAICompatTTS, build_engines)
from mod_ask_server.engines import base as engine_base
from mod_ask_server.errors import ConfigError, EngineError, EngineTimeout
from mod_ask_server.wavio import PLAYABLE_RATES, build_wav, parse_wav, pcm16_samples

# 測試用「金鑰」在執行時組出來；它們不是任何真實服務的金鑰
KEY = "test-" + "key-" + "x" * 12


# ---------- 假引擎 ----------

class FakeEngineTests(unittest.TestCase):
    def test_fake_stt_fixed_text(self):
        self.assertEqual(FakeSTT("固定文字").transcribe(make_wav(1)), "固定文字")
        self.assertEqual(FakeSTT("").transcribe(make_wav(1)), "")  # 空字串＝模擬辨識不到

    def test_fake_stt_by_length_and_silence(self):
        stt = FakeSTT()
        self.assertEqual(stt.transcribe(make_wav(0.5)), "（測試）你好")
        self.assertIn("今天天氣", stt.transcribe(make_wav(3)))
        self.assertIn("比較長", stt.transcribe(make_wav(8)))
        self.assertEqual(stt.transcribe(make_wav(2, silent=True)), "")

    def test_fake_stt_rejects_garbage(self):
        with self.assertRaises(EngineError):
            FakeSTT().transcribe(b"not a wav")

    def test_fake_llm_format(self):
        out = FakeLLM().complete("sys", "你好嗎？")
        self.assertEqual(out, "你問的是：你好嗎。這是測試伺服器的假回答。")
        long = FakeLLM().complete("sys", "甲" * 100)
        self.assertIn("…", long)
        self.assertLessEqual(len(long), 70)
        inner = FakeLLM().complete("sys", "你好。我是誰？再見")
        self.assertEqual(inner.count("。"), 2)  # 問句內的標點不會多出句子

    def test_fake_tts_is_16k_mono_pcm16_quiet_and_scaled_by_text(self):
        tts = FakeTTS()
        short = parse_wav(tts.synthesize("好"))
        mid = parse_wav(tts.synthesize("你好，今天天氣很好喔，我們一起出去玩吧"))
        huge = parse_wav(tts.synthesize("你" * 1000))
        for w in (short, mid, huge):
            self.assertEqual((w.sample_rate, w.channels, w.bits), (16000, 1, 16))
        self.assertAlmostEqual(short.duration, 0.8, places=2)       # 最短
        self.assertGreater(mid.duration, short.duration)
        self.assertAlmostEqual(huge.duration, 6.0, places=2)         # 最長
        peak = max(abs(s) for s in pcm16_samples(mid.pcm))
        self.assertGreater(peak, 500)                                  # 聽得到
        self.assertLess(peak, 32767 * 0.2)                             # 但音量小
        self.assertEqual(tts.synthesize("你好"), tts.synthesize("你好"))  # 決定性
        self.assertEqual(FakeTTS.sample_rate, 16000)

    def test_fake_tts_empty_text_still_valid(self):
        w = parse_wav(FakeTTS().synthesize(""))
        self.assertGreater(w.frames, 0)

    def test_protocols_accept_fakes_and_reject_others(self):
        self.assertIsInstance(FakeSTT(), engine_base.STTEngine)
        self.assertIsInstance(FakeLLM(), engine_base.LLMEngine)
        self.assertIsInstance(FakeTTS(), engine_base.TTSEngine)
        self.assertNotIsInstance(object(), engine_base.TTSEngine)


# ---------- OpenAI 相容：請求格式（本機假上游） ----------

def parse_multipart(headers: dict, body: bytes):
    ctype = headers.get("Content-Type") or headers.get("content-type")
    msg = email.message_from_bytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body,
                                   policy=email.policy.HTTP)
    parts = {}
    for p in msg.iter_parts():
        name = p.get_param("name", header="content-disposition")
        parts[name] = p
    return ctype, parts


def header(req: dict, name: str):
    for k, v in req["headers"].items():
        if k.lower() == name.lower():
            return v
    return None


class OpenAICompatSTTTests(unittest.TestCase):
    def setUp(self):
        self.stub = start_stub(self)
        self.stub.responses["/v1/audio/transcriptions"] = (
            200, "application/json", json.dumps({"text": " 你好世界 "}).encode(), 0)

    def make(self, **kw):
        kw.setdefault("use_env_proxy", False)
        return OpenAICompatSTT(self.stub.base, "stt-model-x", **kw)

    def test_request_format(self):
        wav = make_wav(1)
        out = self.make(api_key=KEY, language="zh").transcribe(wav)
        self.assertEqual(out, "你好世界")
        (req,) = self.stub.requests
        self.assertEqual(req["path"], "/v1/audio/transcriptions")        # {base}/audio/transcriptions
        self.assertEqual(header(req, "Authorization"), "Bearer " + KEY)
        ctype, parts = parse_multipart(req["headers"], req["body"])
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertEqual(parts["model"].get_content(), "stt-model-x")
        self.assertEqual(parts["language"].get_content(), "zh")
        self.assertEqual(parts["response_format"].get_content(), "json")
        f = parts["file"]
        self.assertEqual(f.get_filename(), "audio.wav")
        self.assertEqual(f.get_content_type(), "audio/wav")
        self.assertEqual(f.get_payload(decode=True), wav)               # 原樣上傳 WAV

    def test_no_key_means_no_authorization_header_and_no_language_field(self):
        self.make().transcribe(make_wav(1))
        (req,) = self.stub.requests
        self.assertIsNone(header(req, "Authorization"))
        _, parts = parse_multipart(req["headers"], req["body"])
        self.assertNotIn("language", parts)

    def test_extra_fields(self):
        self.make(extra_fields={"temperature": 0, "prompt": "繁體中文"}).transcribe(make_wav(1))
        _, parts = parse_multipart(self.stub.requests[0]["headers"], self.stub.requests[0]["body"])
        self.assertEqual(parts["temperature"].get_content(), "0")
        self.assertEqual(parts["prompt"].get_payload(decode=True).decode("utf-8"), "繁體中文")

    def test_base_url_trailing_slash_is_normalized(self):
        OpenAICompatSTT(self.stub.base + "/", "m", use_env_proxy=False).transcribe(make_wav(1))
        self.assertEqual(self.stub.requests[0]["path"], "/v1/audio/transcriptions")

    def test_bad_responses(self):
        for status, body in ((500, b"oops"), (401, b"{}"), (200, b"not json"),
                             (200, b'{"nope": 1}'), (200, b'{"text": 5}'), (200, b"[1]")):
            self.stub.responses["/v1/audio/transcriptions"] = (status, "application/json", body, 0)
            with self.assertRaises(EngineError, msg=(status, body)):
                self.make().transcribe(make_wav(1))

    def test_error_message_never_contains_upstream_body_or_key(self):
        self.stub.responses["/v1/audio/transcriptions"] = (
            500, "text/plain", ("echo " + KEY + " 小朋友的話").encode(), 0)
        with self.assertRaises(EngineError) as cm:
            self.make(api_key=KEY).transcribe(make_wav(1))
        self.assertNotIn(KEY, str(cm.exception))
        self.assertNotIn("小朋友", str(cm.exception))
        self.assertIn("500", str(cm.exception))


class OpenAICompatLLMTests(unittest.TestCase):
    def setUp(self):
        self.stub = start_stub(self)
        self.set_reply("好的。")

    def set_reply(self, content, status=200):
        body = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]})
        self.stub.responses["/v1/chat/completions"] = (status, "application/json", body.encode(), 0)

    def make(self, **kw):
        kw.setdefault("use_env_proxy", False)
        return OpenAICompatLLM(self.stub.base, "llm-model-x", **kw)

    def test_request_format(self):
        out = self.make(api_key=KEY, max_tokens=123, temperature=0.3).complete("系統提示", "天空為什麼是藍的")
        self.assertEqual(out, "好的。")
        (req,) = self.stub.requests
        self.assertEqual(req["path"], "/v1/chat/completions")           # {base}/chat/completions
        self.assertEqual(header(req, "Authorization"), "Bearer " + KEY)
        self.assertEqual(header(req, "Content-Type"), "application/json")
        body = json.loads(req["body"].decode("utf-8"))
        self.assertEqual(body["model"], "llm-model-x")
        self.assertEqual(body["messages"], [{"role": "system", "content": "系統提示"},
                                            {"role": "user", "content": "天空為什麼是藍的"}])
        self.assertEqual(body["max_tokens"], 123)
        self.assertEqual(body["temperature"], 0.3)
        self.assertIs(body["stream"], False)

    def test_extra_body_can_override(self):
        self.make(extra_body={"top_p": 0.9, "stream": False}).complete("s", "u")
        body = json.loads(self.stub.requests[0]["body"])
        self.assertEqual(body["top_p"], 0.9)

    def test_no_key_no_authorization(self):
        self.make().complete("s", "u")
        self.assertIsNone(header(self.stub.requests[0], "Authorization"))

    def test_response_cleanup(self):
        self.set_reply("<think>先想一下……</think>\n  答案是這樣。 ")
        self.assertEqual(self.make().complete("s", "u"), "答案是這樣。")
        self.set_reply([{"type": "text", "text": "甲"}, {"type": "text", "text": "乙"}])
        self.assertEqual(self.make().complete("s", "u"), "甲乙")

    def test_bad_responses(self):
        self.set_reply("x", status=429)
        with self.assertRaises(EngineError):
            self.make().complete("s", "u")
        for body in (b"{}", b'{"choices": []}', b'{"choices": [{"message": {}}]}',
                     b'{"choices": [{"message": {"content": null}}]}', b"nonsense"):
            self.stub.responses["/v1/chat/completions"] = (200, "application/json", body, 0)
            with self.assertRaises(EngineError, msg=body):
                self.make().complete("s", "u")


def pcm_bytes(n=2400):
    return struct.pack("<%dh" % n, *[(i % 100) * 50 for i in range(n)])


class OpenAICompatTTSTests(unittest.TestCase):
    def setUp(self):
        self.stub = start_stub(self)

    def make(self, **kw):
        kw.setdefault("use_env_proxy", False)
        return OpenAICompatTTS(self.stub.base, "tts-model-x", **kw)

    def test_request_format_wav(self):
        wav = build_wav(pcm_bytes(), 16000)
        self.stub.responses["/v1/audio/speech"] = (200, "audio/wav", wav, 0)
        out = self.make(api_key=KEY, voice="v1").synthesize("你好，小朋友")
        self.assertEqual(out, wav)
        (req,) = self.stub.requests
        self.assertEqual(req["path"], "/v1/audio/speech")                 # {base}/audio/speech
        self.assertEqual(header(req, "Authorization"), "Bearer " + KEY)
        self.assertEqual(json.loads(req["body"].decode("utf-8")),
                         {"model": "tts-model-x", "input": "你好，小朋友", "voice": "v1",
                          "response_format": "wav"})

    def test_pcm_is_wrapped_into_wav_with_configured_rate(self):
        pcm = pcm_bytes()
        self.stub.responses["/v1/audio/speech"] = (200, "audio/pcm", pcm, 0)
        out = self.make(response_format="pcm", sample_rate=24000).synthesize("你好")
        body = json.loads(self.stub.requests[0]["body"])
        self.assertEqual(body["response_format"], "pcm")
        w = parse_wav(out)
        self.assertEqual((w.sample_rate, w.channels, w.bits), (24000, 1, 16))
        self.assertEqual(w.pcm, pcm)                                      # 不重取樣、資料原樣

    def test_odd_pcm_length_is_trimmed(self):
        self.stub.responses["/v1/audio/speech"] = (200, "audio/pcm", pcm_bytes(10) + b"\x01", 0)
        w = parse_wav(self.make(response_format="pcm").synthesize("你好"))
        self.assertEqual(w.frames, 10)

    def test_empty_audio_and_http_errors(self):
        self.stub.responses["/v1/audio/speech"] = (200, "audio/wav", b"", 0)
        with self.assertRaises(EngineError):
            self.make().synthesize("你好")
        self.stub.responses["/v1/audio/speech"] = (503, "text/plain", b"busy", 0)
        with self.assertRaises(EngineError):
            self.make().synthesize("你好")

    def test_invalid_format_rejected(self):
        with self.assertRaises(ValueError):
            OpenAICompatTTS(self.stub.base, "m", response_format="mp3")


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.stub = start_stub(self)
        self.stub.responses["/v1/chat/completions"] = (
            200, "application/json",
            b'{"choices":[{"message":{"content":"ok"}}]}', 0)

    def llm(self, **kw):
        return OpenAICompatLLM(self.stub.base, "m", use_env_proxy=False, **kw)

    def test_timeout_becomes_engine_timeout(self):
        self.stub.responses["/v1/chat/completions"] = (200, "application/json", b"{}", 1.5)
        with self.assertRaises(EngineTimeout):
            self.llm(timeout_s=10).complete("s", "u", timeout=0.2)   # 呼叫端給的剩餘時間較短

    def test_configured_timeout_is_also_enforced(self):
        self.stub.responses["/v1/chat/completions"] = (200, "application/json", b"{}", 1.5)
        with self.assertRaises(EngineTimeout):
            self.llm(timeout_s=0.5).complete("s", "u")

    def test_connection_refused_is_engine_error(self):
        llm = OpenAICompatLLM("http://127.0.0.1:%d/v1" % free_port(), "m", use_env_proxy=False)
        with self.assertRaises(EngineError) as cm:
            llm.complete("s", "u")
        self.assertNotIsInstance(cm.exception, EngineTimeout)

    def test_redirects_are_not_followed(self):
        # 否則 Authorization 會被帶去別的位址
        self.stub.responses["/v1/chat/completions"] = (302, "text/plain", b"", 0)
        self.stub.extra_headers["/v1/chat/completions"] = {"Location": "/v1/elsewhere"}
        with self.assertRaises(EngineError):
            self.llm(api_key=KEY).complete("s", "u")
        self.assertEqual([r["path"] for r in self.stub.requests], ["/v1/chat/completions"])

    def test_oversized_response_is_rejected(self):
        from mod_ask_server.engines import openai_compat as oc
        self.stub.responses["/v1/chat/completions"] = (200, "application/json",
                                                       b"x" * 5000, 0)
        with mock.patch.object(oc, "MAX_TEXT_RESPONSE", 1000):
            with self.assertRaises(EngineError):
                self.llm().complete("s", "u")


class MockedTransportTests(unittest.TestCase):
    """用 unittest.mock 取代 urllib 的 open：確認組出來的 Request 長什麼樣，完全不碰網路。"""

    def run_with_mock(self, call, payload=b'{"choices":[{"message":{"content":"ok"}}]}'):
        captured = {}

        def fake_open(opener, req, data=None, timeout=None):
            captured["req"], captured["timeout"] = req, timeout
            resp = mock.MagicMock()
            resp.read.return_value = payload
            resp.__enter__.return_value = resp
            return resp

        with mock.patch.object(urllib.request.OpenerDirector, "open", fake_open):
            result = call()
        return result, captured

    def test_llm_request_object(self):
        llm = OpenAICompatLLM("https://ai.example.com/v1/", "m", api_key=KEY, timeout_s=7)
        out, cap = self.run_with_mock(lambda: llm.complete("系統", "問題"))
        self.assertEqual(out, "ok")
        req = cap["req"]
        self.assertEqual(req.full_url, "https://ai.example.com/v1/chat/completions")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(cap["timeout"], 7)

    def test_timeout_is_min_of_configured_and_remaining(self):
        llm = OpenAICompatLLM("https://ai.example.com/v1", "m", timeout_s=7)
        _, cap = self.run_with_mock(lambda: llm.complete("s", "u", timeout=2.5))
        self.assertEqual(cap["timeout"], 2.5)

    def test_mocked_http_error_hides_body(self):
        def boom(opener, req, data=None, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 418, "teapot", {}, io.BytesIO(b"secret"))
        llm = OpenAICompatLLM("https://ai.example.com/v1", "m")
        with mock.patch.object(urllib.request.OpenerDirector, "open", boom):
            with self.assertRaises(EngineError) as cm:
                llm.complete("s", "u")
        self.assertIn("418", str(cm.exception))
        self.assertNotIn("secret", str(cm.exception))


# ---------- 設定：建立引擎、金鑰只讀環境變數 ----------

def cfg(**engines):
    return config_from_dict({k: v for k, v in engines.items()})


def compat(kind, **extra):
    block = {"base_url": "https://ai.example.com/v1", "model": "your-%s-model" % kind}
    block.update(extra)
    return {"type": "openai_compat", "openai_compat": block}


class BuildEnginesTests(unittest.TestCase):
    def test_defaults_are_fakes(self):
        e = build_engines(config_from_dict({}), environ={})
        self.assertIsInstance(e.stt, FakeSTT)
        self.assertIsInstance(e.llm, FakeLLM)
        self.assertIsInstance(e.tts, FakeTTS)

    def test_key_comes_only_from_environment(self):
        c = cfg(stt=compat("stt"), llm=compat("llm"), tts=compat("tts"))
        env = {"ASK_STT_API_KEY": KEY + "-stt", "ASK_LLM_API_KEY": KEY + "-llm",
               "ASK_TTS_API_KEY": KEY + "-tts", "UNRELATED": "x"}
        e = build_engines(c, environ=env)
        self.assertEqual(e.stt._http._api_key, KEY + "-stt")
        self.assertEqual(e.llm._http._api_key, KEY + "-llm")
        self.assertEqual(e.tts._http._api_key, KEY + "-tts")
        self.assertEqual(e.llm._http.base_url, "https://ai.example.com/v1")

    def test_key_env_name_is_configurable_and_missing_key_warns(self):
        c = cfg(llm=compat("llm", api_key_env="MY_OWN_LLM_KEY"))
        e = build_engines(c, environ={"MY_OWN_LLM_KEY": KEY, "ASK_LLM_API_KEY": "ignored"})
        self.assertEqual(e.llm._http._api_key, KEY)
        with self.assertLogs("mod_ask.engines", level="WARNING") as logs:
            e = build_engines(cfg(llm=compat("llm")), environ={})
        self.assertIsNone(e.llm._http._api_key)
        self.assertIn("ASK_LLM_API_KEY", logs.output[0])
        self.assertNotIn(KEY, logs.output[0])

    def test_real_environment_is_default_source(self):
        with mock.patch.dict("os.environ", {"ASK_LLM_API_KEY": KEY}):
            e = build_engines(cfg(llm=compat("llm")))
        self.assertEqual(e.llm._http._api_key, KEY)

    def test_inactive_blocks_are_not_validated(self):
        # 範例設定檔把三種引擎的區塊都寫著，只有 type 指到的那塊會被檢查
        c = cfg(stt={"type": "fake", "openai_compat": {"base_url": "ftp://bad", "typo_key": 1}})
        build_engines(c, environ={})

    def test_invalid_openai_compat_blocks(self):
        bad = [
            compat("stt", base_url="ftp://ai.example.com"),
            compat("stt", base_url="ai.example.com/v1"),
            compat("stt", base_url=""),
            compat("stt", base_url="https://user:pw" + chr(64) + "ai.example.com/v1"),  # 帳密不能放網址
            compat("stt", model=""),
            compat("stt", api_key_env="sk-" + "a" * 20),                   # 把金鑰本身貼成「變數名稱」
            compat("stt", api_key_env="has space"),
            compat("stt", timeout_s=0),
            compat("stt", api_key="nope"),                                  # 沒有 api_key 這個欄位
            compat("stt", extra_fields="x"),
        ]
        for stt in bad:
            with self.assertRaises(ConfigError, msg=str(stt)):
                build_engines(cfg(stt=stt), environ={})
        for llm in (compat("llm", max_tokens=0), compat("llm", temperature=5),
                    compat("llm", extra_body=[1])):
            with self.assertRaises(ConfigError):
                build_engines(cfg(llm=llm), environ={})
        for tts in (compat("tts", response_format="mp3"), compat("tts", voice=5)):
            with self.assertRaises(ConfigError):
                build_engines(cfg(tts=tts), environ={})

    def test_config_errors_never_echo_values(self):
        secret = "sk-" + "Z" * 24
        for blk in (compat("stt", api_key_env=secret),
                    compat("stt", base_url="https://u:" + secret + chr(64) + "ai.example.com"),
                    compat("stt", api_key=secret)):
            with self.assertRaises(ConfigError) as cm:
                build_engines(cfg(stt=blk), environ={})
            self.assertNotIn(secret, str(cm.exception))

    def test_fake_blocks_reject_unknown_keys(self):
        for c in (cfg(stt={"fake": {"nope": 1}}), cfg(llm={"fake": {"nope": 1}}),
                  cfg(tts={"fake": {"nope": 1}})):
            with self.assertRaises(ConfigError):
                build_engines(c, environ={})

    def test_fake_stt_fixed_text_from_config(self):
        e = build_engines(cfg(stt={"fake": {"fixed_text": "固定"}}), environ={})
        self.assertEqual(e.stt.transcribe(make_wav(1)), "固定")


class CustomFactoryTests(unittest.TestCase):
    def test_custom_factory_is_loaded(self):
        c = cfg(stt={"type": "custom", "custom": {"factory": "_custom_engines:make_stt",
                                                  "text": "來自自訂引擎"}})
        e = build_engines(c, environ={})
        self.assertEqual(e.stt.transcribe(b"x"), "來自自訂引擎")

    def test_bad_factories(self):
        for factory in ("", "nocolon", "no_such_module_xyz:make", "_custom_engines:missing",
                        "_custom_engines:make_wrong"):
            c = cfg(llm={"type": "custom", "custom": {"factory": factory}})
            with self.assertRaises(ConfigError, msg=factory):
                build_engines(c, environ={})


# ---------- TTS 取樣率（SERVER_API §3.2：只能送裝置播得了的取樣率） ----------

class TtsSampleRateConfigTests(unittest.TestCase):
    def test_playable_rate_list_matches_spec(self):
        self.assertEqual(set(PLAYABLE_RATES),
                         {8000, 16000, 32000, 44100, 48000, 24000, 22050, 12000, 11025})

    def test_pcm_sample_rate_must_be_playable(self):
        for rate in sorted(PLAYABLE_RATES):  # 24000（常見 TTS 輸出）也在其中，不必重取樣
            e = build_engines(cfg(tts=compat("tts", response_format="pcm", sample_rate=rate)),
                              environ={})
            self.assertEqual(e.tts.sample_rate, rate)
        for rate in (10000, 18000, 22000, 37800, 96000, 7999, 0):
            with self.assertRaises(ConfigError, msg=rate):
                build_engines(cfg(tts=compat("tts", response_format="pcm", sample_rate=rate)),
                              environ={})


if __name__ == "__main__":
    unittest.main()
