# SPDX-License-Identifier: MIT
"""WAV 解析與驗證、test WAV 產生工具。"""
import io
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

import _helpers
from _helpers import make_wav
from mod_ask_server.wavio import (MIN_SECONDS, WavError, build_wav, parse_wav,
                                  pcm16_samples, samples_to_pcm16, validate_upload)


def chunk(cid: bytes, payload: bytes, size: int | None = None) -> bytes:
    size = len(payload) if size is None else size
    return cid + struct.pack("<I", size) + payload + (b"\0" if len(payload) % 2 else b"")


FMT16K = chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 16000, 32000, 2, 16))


def riff(*chunks: bytes) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


class ParseTests(unittest.TestCase):
    def test_build_header_is_44_bytes_and_readable_by_wave_module(self):
        pcm = struct.pack("<4h", 1, -2, 3, -4)
        data = build_wav(pcm, 16000)
        self.assertEqual(len(data), 44 + len(pcm))
        with wave.open(io.BytesIO(data)) as w:  # 用標準函式庫交叉驗證
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 16000))
            self.assertEqual(w.getnframes(), 4)
            self.assertEqual(w.readframes(4), pcm)

    def test_max_size_matches_spec(self):
        # SERVER_API §3.1：15 s 的標準檔是 480,044 B
        self.assertEqual(len(build_wav(bytes(15 * 16000 * 2))), 480044)

    def test_roundtrip_and_wave_module_file(self):
        src = make_wav(1.0)
        w = parse_wav(src)
        self.assertEqual((w.sample_rate, w.channels, w.bits), (16000, 1, 16))
        self.assertEqual(w.frames, 16000)
        self.assertAlmostEqual(w.duration, 1.0)
        self.assertEqual(build_wav(w.pcm), src)

    def test_skips_list_chunk_and_odd_padding(self):
        pcm = bytes(range(8))
        data = riff(chunk(b"LIST", b"INFOabc"), FMT16K, chunk(b"fact", b"x" * 5),
                    chunk(b"data", pcm))
        self.assertEqual(parse_wav(data).pcm, pcm)

    def test_streaming_sizes_zero_and_ffffffff_mean_until_end(self):
        pcm = bytes(range(10))
        for size in (0xFFFFFFFF, 0):
            data = riff(FMT16K, b"data" + struct.pack("<I", size) + pcm)
            self.assertEqual(parse_wav(data).pcm, pcm, hex(size))

    def test_trailing_partial_sample_is_dropped(self):
        data = riff(FMT16K, chunk(b"data", bytes(range(7))))
        self.assertEqual(parse_wav(data).pcm, bytes(range(6)))

    def test_empty_data_chunk_is_parsed_as_zero_frames(self):
        w = parse_wav(riff(FMT16K, chunk(b"data", b"")))
        self.assertEqual(w.frames, 0)

    def test_pcm16_samples_roundtrip(self):
        pcm = struct.pack("<3h", 1, -32768, 32767)
        arr = pcm16_samples(pcm)
        self.assertEqual(list(arr), [1, -32768, 32767])
        self.assertEqual(samples_to_pcm16(arr), pcm)


class RejectTests(unittest.TestCase):
    def assertBad(self, data: bytes):
        with self.assertRaises(WavError) as cm:
            parse_wav(data)
        self.assertEqual(cm.exception.code, "bad_audio")

    def test_not_wav(self):
        self.assertBad(b"")
        self.assertBad(b"hello world, definitely not a wav file")
        self.assertBad(b"RIFF" + bytes(4) + b"AVI ")
        self.assertBad(b"\xff\xfb\x90\x00" * 100)  # 像 MP3

    def test_non_pcm_format_tags(self):
        for tag in (3, 0xFFFE, 85):  # float、extensible、mp3
            fmt = chunk(b"fmt ", struct.pack("<HHIIHH", tag, 1, 16000, 32000, 2, 16))
            self.assertBad(riff(fmt, chunk(b"data", bytes(4))))

    def test_fmt_problems(self):
        self.assertBad(riff(chunk(b"fmt ", b"\x01\x00\x01\x00"), chunk(b"data", bytes(4))))
        zero_ch = chunk(b"fmt ", struct.pack("<HHIIHH", 1, 0, 16000, 0, 0, 16))
        self.assertBad(riff(zero_ch, chunk(b"data", bytes(4))))
        weird_bits = chunk(b"fmt ", struct.pack("<HHIIHH", 1, 1, 16000, 0, 2, 12))
        self.assertBad(riff(weird_bits, chunk(b"data", bytes(4))))

    def test_data_before_fmt(self):
        self.assertBad(riff(chunk(b"data", bytes(4)), FMT16K))

    def test_no_data_chunk(self):
        self.assertBad(riff(FMT16K))
        self.assertBad(riff(FMT16K, chunk(b"LIST", b"abcd")))

    def test_truncated_data(self):
        # 標頭宣稱 1000 B，實際只有 10 B（上傳中斷）
        self.assertBad(riff(FMT16K, b"data" + struct.pack("<I", 1000) + bytes(10)))


class ValidateTests(unittest.TestCase):
    def check(self, wav: bytes, max_seconds: float = 15):
        validate_upload(parse_wav(wav), max_seconds=max_seconds)

    def assertCode(self, wav: bytes, code: str, max_seconds: float = 15):
        with self.assertRaises(WavError) as cm:
            self.check(wav, max_seconds)
        self.assertEqual(cm.exception.code, code)
        return str(cm.exception)

    def test_normal(self):
        self.check(make_wav(2.0))
        self.check(make_wav(MIN_SECONDS))       # 剛好 0.3 s 可以
        self.check(make_wav(15.0))              # 剛好 15 s 可以
        self.check(make_wav(15.0, amp=0, silent=True))

    def test_wrong_format(self):
        self.assertCode(make_wav(1, rate=8000), "bad_audio")
        self.assertCode(make_wav(1, rate=44100), "bad_audio")
        self.assertCode(make_wav(1, channels=2), "bad_audio")
        self.assertCode(make_wav(1, width=1), "bad_audio")

    def test_too_short(self):
        self.assertCode(make_wav(0.29), "too_short")
        self.assertCode(make_wav(0.0), "too_short")
        self.assertCode(make_wav(0.1), "too_short")

    def test_too_long(self):
        msg = self.assertCode(make_wav(15.01), "too_long")
        self.assertEqual(msg, "audio longer than 15 s")  # 與 SERVER_API §3.3 範例同文
        self.assertCode(make_wav(30), "too_long")
        self.assertCode(make_wav(2.0), "too_long", max_seconds=1)

    def test_format_checked_before_length(self):
        # 格式錯又太長：先報格式
        self.assertCode(make_wav(20, rate=8000), "bad_audio")


class MakeTestWavToolTests(unittest.TestCase):
    TOOL = _helpers.SERVER_DIR / "tools" / "make_test_wav.py"

    def run_tool(self, *args: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "out.wav"
        r = subprocess.run([sys.executable, str(self.TOOL), str(out), *args],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def test_default_is_valid_upload(self):
        out = self.run_tool()
        w = parse_wav(out.read_bytes())
        validate_upload(w, max_seconds=15)
        self.assertAlmostEqual(w.duration, 2.0)
        self.assertGreater(max(abs(s) for s in pcm16_samples(w.pcm)), 1000)

    def test_variants(self):
        silent = parse_wav(self.run_tool("--kind", "silence", "--seconds", "1").read_bytes())
        self.assertEqual(max(abs(s) for s in pcm16_samples(silent.pcm)), 0)
        bad = parse_wav(self.run_tool("--rate", "44100", "--seconds", "1").read_bytes())
        with self.assertRaises(WavError):
            validate_upload(bad, max_seconds=15)


if __name__ == "__main__":
    unittest.main()
