#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""產生測試用 WAV（只用標準函式庫的 wave 模組）。

預設是 16 kHz／16 bit／單聲道、2 秒、帶音量起伏的柔和音（假 STT 會當成「有人說話」）。

範例：
    python3 tools/make_test_wav.py question.wav                 # 2 秒正常錄音
    python3 tools/make_test_wav.py short.wav --seconds 0.1      # 太短（400 too_short）
    python3 tools/make_test_wav.py long.wav --seconds 20        # 太長（413 too_long）
    python3 tools/make_test_wav.py quiet.wav --kind silence     # 靜音（假 STT 回「沒聽清楚」）
    python3 tools/make_test_wav.py bad.wav --rate 44100         # 格式錯誤（400 bad_audio）
    python3 tools/make_test_wav.py stereo.wav --channels 2      # 格式錯誤（400 bad_audio）
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import sys
import wave


def make_frames(kind: str, seconds: float, rate: int, channels: int, amp: int) -> bytes:
    n = int(seconds * rate)
    rng = random.Random(1234)  # 固定種子：每次產生的檔案一樣
    out = bytearray()
    for i in range(n):
        t = i / rate
        if kind == "silence":
            v = 0
        elif kind == "noise":
            v = int(rng.uniform(-1, 1) * amp)
        else:  # tone：220 Hz 基音加一點泛音，音量以 3 Hz 起伏，像有人在說話
            env = 0.55 + 0.45 * math.sin(2 * math.pi * 3 * t)
            v = int(amp * env * (0.7 * math.sin(2 * math.pi * 220 * t)
                                 + 0.3 * math.sin(2 * math.pi * 440 * t)))
        out += struct.pack("<h", max(-32768, min(32767, v))) * channels
    return bytes(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="產生測試用 WAV")
    ap.add_argument("out", help="輸出檔名，例如 question.wav")
    ap.add_argument("--seconds", type=float, default=2.0, help="長度（秒），預設 2")
    ap.add_argument("--kind", choices=("tone", "silence", "noise"), default="tone")
    ap.add_argument("--rate", type=int, default=16000, help="取樣率，預設 16000")
    ap.add_argument("--channels", type=int, default=1, help="聲道數，預設 1")
    ap.add_argument("--amplitude", type=int, default=6000, help="振幅（0–32767），預設 6000")
    args = ap.parse_args(argv)
    if args.seconds <= 0 or not 1 <= args.channels <= 8 or args.rate < 1:
        print("error: invalid arguments", file=sys.stderr)
        return 2
    with wave.open(args.out, "wb") as w:
        w.setnchannels(args.channels)
        w.setsampwidth(2)
        w.setframerate(args.rate)
        w.writeframes(make_frames(args.kind, args.seconds, args.rate, args.channels,
                                  max(0, min(32767, args.amplitude))))
    print("wrote %s (%.2f s, %d Hz, %d ch, 16 bit)" % (args.out, args.seconds, args.rate,
                                                      args.channels))
    return 0


if __name__ == "__main__":
    sys.exit(main())
