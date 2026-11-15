# SPDX-License-Identifier: MIT
"""設定檔載入與驗證、token 雜湊與檢查、hash_token 工具、命令列啟動／關閉。"""
import hashlib
import json
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

import _helpers
from _helpers import SERVER_DIR, free_port
from mod_ask_server.auth import TokenAuth, hash_token
from mod_ask_server.config import Config, config_from_dict, load_config
from mod_ask_server.engines import build_engines
from mod_ask_server.errors import ConfigError


class ConfigDefaultsTests(unittest.TestCase):
    def test_defaults_match_spec(self):
        c = config_from_dict({})
        self.assertEqual((c.server.host, c.server.port), ("127.0.0.1", 8787))
        self.assertEqual(c.limits.max_seconds, 15)
        self.assertEqual(c.limits.body_cap, 480044)                  # SERVER_API §3.1
        self.assertEqual(c.auth.token_sha256, ())
        self.assertEqual((c.stt.kind, c.llm.kind, c.tts.kind), ("fake",) * 3)
        self.assertEqual(c.child_mode.empty_stt, "speak")
        self.assertEqual(c.qa_log.retention_days, 30)
        self.assertTrue(c.qa_log.enabled)
        self.assertEqual(c.qa_log.path, "./data/qa_log.jsonl")
        self.assertEqual(c.display.font_path, "")
        self.assertFalse(c.quota.hours_enabled)

    def test_body_cap_follows_max_seconds_or_explicit(self):
        self.assertEqual(config_from_dict({"limits": {"max_seconds": 10}}).limits.body_cap,
                         44 + 10 * 32000)
        self.assertEqual(config_from_dict({"limits": {"max_body_bytes": 100000}}).limits.body_cap,
                         100000)

    def test_hours_parsing(self):
        c = config_from_dict({"quota": {"allowed_hours": {"enabled": True, "start": "07:00",
                                                          "end": "20:30"}}})
        self.assertEqual((c.quota.hours_start, c.quota.hours_end), (420, 1230))

    def test_relative_paths_resolve_against_config_dir(self):
        c = config_from_dict({}, base_dir="/some/dir")
        self.assertEqual(str(c.resolve("./data/x.jsonl")), "/some/dir/data/x.jsonl")
        self.assertEqual(str(c.resolve("/abs/y")), "/abs/y")


class ConfigValidationTests(unittest.TestCase):
    def check_bad(self, raw):
        with self.assertRaises(ConfigError, msg=json.dumps(raw)):
            config_from_dict(raw)

    def test_rejects_bad_values(self):
        for raw in (
            [], {"unknown_section": {}}, {"server": {"prot": 1}}, {"server": []},
            {"server": {"port": "8787"}}, {"server": {"port": 70000}}, {"server": {"port": True}},
            {"server": {"host": ""}}, {"server": {"base_path": "ask-api"}},
            {"server": {"base_path": "/ask-api/"}}, {"server": {"max_concurrent": 0}},
            {"limits": {"max_seconds": 0}}, {"limits": {"max_seconds": "15"}},
            {"limits": {"max_body_bytes": 10}},
            {"auth": {"token_sha256": "abc"}}, {"auth": {"token_sha256": ["short"]}},
            {"auth": {"token_sha256": [123]}}, {"auth": {"token_sha256": ["g" * 64]}},
            {"stt": {"type": "nope"}}, {"stt": {"typo": 1}}, {"stt": {"fake": []}},
            {"child_mode": {"empty_stt": "maybe"}}, {"child_mode": {"max_answer_chars": 1}},
            {"quota": {"per_minute": -1}}, {"quota": {"per_day": 1.5}},
            {"quota": {"allowed_hours": {"start": "7:00"}}},
            {"quota": {"allowed_hours": {"start": "25:00"}}},
            {"quota": {"allowed_hours": {"enabled": True, "start": "08:00", "end": "08:00"}}},
            {"qa_log": {"retention_days": 0}}, {"qa_log": {"path": ""}},
            {"qa_log": {"enabled": "yes"}},
            {"display": {"font_size": 2}},
        ):
            self.check_bad(raw)

    def test_secret_like_keys_get_a_hint_without_echoing_values(self):
        secret = "sk-" + "Q" * 24
        with self.assertRaises(ConfigError) as cm:
            config_from_dict({"stt": {"openai_compat": {}, "api_key": secret}})
        self.assertIn("api_key_env", str(cm.exception))
        self.assertNotIn(secret, str(cm.exception))

    def test_plaintext_token_in_hash_list_is_rejected_without_echo(self):
        plain = "my-device-token-" + secrets.token_hex(8)
        with self.assertRaises(ConfigError) as cm:
            config_from_dict({"auth": {"token_sha256": [plain]}})
        self.assertNotIn(plain, str(cm.exception))

    def test_underscore_keys_are_comments(self):
        c = config_from_dict({"_x": 1, "server": {"_y": 2, "port": 9000},
                              "stt": {"_z": 3, "type": "fake"}})
        self.assertEqual(c.server.port, 9000)

    def test_hashes_are_normalized_to_lowercase(self):
        h = hash_token("abc")
        c = config_from_dict({"auth": {"token_sha256": [" " + h.upper() + " "]}})
        self.assertEqual(c.auth.token_sha256, (h,))

    def test_load_config_errors(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ConfigError):
                load_config(Path(d) / "missing.json")
            p = Path(d) / "c.json"
            p.write_text("{oops", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(p)
            p.write_text('{"server": {"port": 1234}}', encoding="utf-8")
            c = load_config(p)
            self.assertEqual(c.server.port, 1234)
            self.assertEqual(c.base_dir, p.resolve().parent)
        self.assertIsInstance(load_config(None), Config)


class ExampleFilesTests(unittest.TestCase):
    def test_example_config_loads_and_builds(self):
        c = load_config(SERVER_DIR / "config.example.json")
        self.assertEqual((c.server.host, c.server.port), ("127.0.0.1", 8787))
        self.assertEqual(c.auth.token_sha256, ())
        self.assertEqual((c.stt.kind, c.llm.kind, c.tts.kind), ("fake",) * 3)
        build_engines(c, environ={})

    def test_example_openai_compat_blocks_are_valid(self):
        raw = json.loads((SERVER_DIR / "config.example.json").read_text(encoding="utf-8"))
        for name in ("stt", "llm", "tts"):
            raw[name]["type"] = "openai_compat"
        c = config_from_dict(raw, SERVER_DIR)
        e = build_engines(c, environ={})
        self.assertEqual(e.llm._http.base_url, "https://ai.example.com/v1")
        self.assertEqual(e.tts.sample_rate, 24000)

    def test_example_files_contain_no_keys_or_private_addresses(self):
        import re
        for name in ("config.example.json", "child_rules.example.json"):
            text = (SERVER_DIR / name).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._~+/-]{12,}", text))
            self.assertIsNone(re.search(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+", text))
            self.assertNotIn("/Use" + "rs/", text)
        text = (SERVER_DIR / "config.example.json").read_text(encoding="utf-8")
        for url in re.findall(r"https?://[^\"\s]+", text):
            self.assertRegex(url, r"^(https://ai\.example\.com|http://127\.0\.0\.1)")


class TokenAuthTests(unittest.TestCase):
    def setUp(self):
        self.tok = "device-" + secrets.token_hex(16)
        self.auth = TokenAuth([hash_token(self.tok)])

    def test_hash_is_sha256_hex_of_utf8(self):
        self.assertEqual(hash_token("abc"), hashlib.sha256(b"abc").hexdigest())
        self.assertEqual(hash_token("密碼"), hashlib.sha256("密碼".encode()).hexdigest())

    def test_empty_list_means_no_check(self):
        a = TokenAuth([])
        self.assertFalse(a.enabled)
        for h in (None, "", "garbage", "Bearer whatever"):
            self.assertTrue(a.verify(h))

    def test_valid_and_invalid(self):
        self.assertTrue(self.auth.enabled)
        self.assertTrue(self.auth.verify("Bearer " + self.tok))
        self.assertTrue(self.auth.verify("bearer " + self.tok))       # scheme 不分大小寫
        self.assertTrue(self.auth.verify("  Bearer " + self.tok + "  "))
        for h in (None, "", "Bearer", "Bearer ", "Bearer wrong", self.tok,
                  "Basic " + self.tok, "Bearer " + self.tok + "x", "Bearer  " + self.tok[:-1]):
            self.assertFalse(self.auth.verify(h), h)

    def test_multiple_tokens(self):
        other = "other-" + secrets.token_hex(8)
        a = TokenAuth([hash_token(self.tok), hash_token(other)])
        self.assertTrue(a.verify("Bearer " + other))
        self.assertTrue(a.verify("Bearer " + self.tok))
        self.assertFalse(a.verify("Bearer nope"))

    def test_stored_hash_is_not_usable_as_token(self):
        self.assertFalse(self.auth.verify("Bearer " + hash_token(self.tok)))


def run_module(module, *, stdin=None, timeout=30):
    return subprocess.run([sys.executable, "-m", module], input=stdin, cwd=SERVER_DIR,
                          capture_output=True, text=True, timeout=timeout)


class HashTokenToolTests(unittest.TestCase):
    def test_reads_stdin_prints_only_hash(self):
        tok = "secret-" + secrets.token_hex(12)
        r = run_module("mod_ask_server.hash_token", stdin=tok + "\n")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), hashlib.sha256(tok.encode()).hexdigest())
        self.assertNotIn(tok, r.stdout)       # 不印出明文
        self.assertNotIn(tok, r.stderr)

    def test_trailing_newline_only_is_stripped(self):
        h = lambda s: hashlib.sha256(s.encode()).hexdigest()
        self.assertEqual(run_module("mod_ask_server.hash_token", stdin="abc").stdout.strip(), h("abc"))
        self.assertEqual(run_module("mod_ask_server.hash_token", stdin="abc\r\n").stdout.strip(), h("abc"))
        self.assertEqual(run_module("mod_ask_server.hash_token", stdin="a b\n").stdout.strip(), h("a b"))

    def test_empty_input_fails(self):
        for stdin in ("", "\n", "\r\n"):
            r = run_module("mod_ask_server.hash_token", stdin=stdin)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stdout, "")

    def test_output_can_go_straight_into_config(self):
        tok = secrets.token_urlsafe(24)
        h = run_module("mod_ask_server.hash_token", stdin=tok).stdout.strip()
        c = config_from_dict({"auth": {"token_sha256": [h]}})
        self.assertTrue(TokenAuth(c.auth.token_sha256).verify("Bearer " + tok))


class CommandLineTests(unittest.TestCase):
    def test_version_and_help(self):
        r = subprocess.run([sys.executable, "-m", "mod_ask_server", "--version"], cwd=SERVER_DIR,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("mod-ask-server", r.stdout)

    def test_bad_config_exits_2_with_message(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.json"
            p.write_text('{"server": {"prot": 1}}', encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "mod_ask_server", "--config", str(p)],
                               cwd=SERVER_DIR, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2)
        self.assertIn("prot", r.stderr)

    def test_port_in_use_exits_2(self):
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        self.addCleanup(s.close)
        r = subprocess.run([sys.executable, "-m", "mod_ask_server", "--port",
                            str(s.getsockname()[1])], cwd=SERVER_DIR, capture_output=True,
                           text=True, timeout=30)
        self.assertEqual(r.returncode, 2)

    def test_starts_serves_and_stops_cleanly_on_sigterm(self):
        """真的把伺服器當程序跑起來：health、ask，然後 SIGTERM，確認程序結束、埠釋放。"""
        port = free_port()
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"qa_log": {"path": str(Path(d) / "qa.jsonl")}}),
                           encoding="utf-8")
            proc = subprocess.Popen(
                [sys.executable, "-m", "mod_ask_server", "--config", str(cfg),
                 "--port", str(port)], cwd=SERVER_DIR, stderr=subprocess.PIPE,
                stdout=subprocess.DEVNULL, text=True)
            lines: "queue.Queue[str]" = queue.Queue()
            reader = threading.Thread(target=lambda: [lines.put(x) for x in proc.stderr],
                                      daemon=True)
            reader.start()
            self.addCleanup(lambda: proc.poll() is None and proc.kill())
            deadline = time.time() + 20
            banner = ""
            while time.time() < deadline and "listening on" not in banner:
                try:
                    banner = lines.get(timeout=0.2)
                except queue.Empty:
                    if proc.poll() is not None:
                        self.fail("server exited early")
            self.assertIn("listening on 127.0.0.1:%d" % port, banner)
            self.assertIn("stt=fake", banner)
            with urllib.request.urlopen("http://127.0.0.1:%d/v1/health" % port, timeout=10) as r:
                self.assertEqual(json.load(r)["api"], "mod-ask/1")
            req = urllib.request.Request(
                "http://127.0.0.1:%d/v1/ask" % port, data=_helpers.make_wav(1), method="POST",
                headers={"Content-Type": "audio/wav", "X-Device-Id": _helpers.DEVICE_ID})
            with urllib.request.urlopen(req, timeout=10) as r:
                self.assertEqual(r.status, 200)
                r.read()
            proc.terminate()
            self.assertEqual(proc.wait(timeout=15), 0)
            reader.join(timeout=5)
            proc.stderr.close()
            # 埠已釋放（沒有人在聽了）、紀錄已寫入
            import socket
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)
            self.assertEqual(len((Path(d) / "qa.jsonl").read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
