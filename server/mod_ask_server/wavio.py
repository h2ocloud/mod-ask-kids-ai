# SPDX-License-Identifier: MIT
"""WAV 解析、驗證與產生（只用標準函式庫，不用已移除的 audioop）。

上傳規格（SERVER_API §3.1）：PCM（format 1）、單聲道、16000 Hz、16 bit，長度 0.3 s 以上、
不超過 max_seconds。回應規格（§3.2）：PCM16 單聲道，取樣率限 PLAYABLE_RATES（建議 16000）。
解析器的寬鬆程度與韌體端 WavStreamParser 一致：
- 會略過 data 前的其他 chunk（LIST 等），fmt 必須在 data 之前；
- data 長度欄位為 0 或 0xFFFFFFFF 時，視為「一直到檔尾」；
- data 結尾不足一個完整樣本的零碎位元組會被丟掉。
"""
from __future__ import annotations

import array
import struct
import sys
from dataclasses import dataclass

from . import SAMPLE_RATE

MIN_SECONDS = 0.3          # SERVER_API §3.1／§3.3 too_short

# 回應音訊允許的取樣率（SERVER_API §3.2）：功放只吃 8000／16000／32000／44100／48000；
# 裝置會把 24000、22050（×2）與 12000、11025（×4）升頻後播放；其他取樣率裝置會當成格式錯誤。
PLAYABLE_RATES = frozenset({8000, 16000, 32000, 44100, 48000,
                            24000, 22050, 12000, 11025})
_U32_UNBOUNDED = 0xFFFFFFFF  # 串流 WAV 常見的「長度未知」


class WavError(ValueError):
    """WAV 不合規。code 是 SERVER_API 的錯誤碼：bad_audio／too_short／too_long。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# WavError.code → HTTP 狀態碼（SERVER_API §3.3）
HTTP_STATUS = {"bad_audio": 400, "too_short": 400, "too_long": 413}


@dataclass(frozen=True)
class WavData:
    sample_rate: int
    channels: int
    bits: int
    pcm: bytes  # 原始樣本（little-endian），長度一定是 block_align 的整數倍

    @property
    def block_align(self) -> int:
        return self.channels * self.bits // 8

    @property
    def frames(self) -> int:
        return len(self.pcm) // self.block_align

    @property
    def duration(self) -> float:
        return self.frames / self.sample_rate


def parse_wav(data: bytes) -> WavData:
    """解析 RIFF/WAVE（只收 PCM format 1）。格式不對丟 WavError('bad_audio', ...)。"""
    n = len(data)
    if n < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavError("bad_audio", "not a RIFF/WAVE file")
    pos = 12
    fmt: tuple[int, int, int] | None = None  # (channels, rate, bits)
    while pos + 8 <= n:
        cid = data[pos:pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        body = pos + 8
        if cid == b"fmt ":
            if size < 16 or body + 16 > n:
                raise WavError("bad_audio", "fmt chunk too short")
            tag, ch, rate, _byte_rate, _align, bits = struct.unpack_from("<HHIIHH", data, body)
            if tag != 1:
                raise WavError("bad_audio", "unsupported WAV format %d, need PCM (1)" % tag)
            if ch < 1 or rate < 1 or bits not in (8, 16, 24, 32):
                raise WavError("bad_audio", "invalid fmt chunk")
            fmt = (ch, rate, bits)
        elif cid == b"data":
            if fmt is None:
                raise WavError("bad_audio", "fmt chunk must come before data chunk")
            ch, rate, bits = fmt
            avail = n - body
            if size == _U32_UNBOUNDED or (size == 0 and avail > 0):
                size = avail  # 串流式 WAV：長度欄位沒填，吃到檔尾
            elif size > avail:
                raise WavError("bad_audio", "data chunk is truncated")
            align = ch * bits // 8
            size -= size % align  # 丟掉不足一個樣本的尾巴
            return WavData(rate, ch, bits, bytes(data[body:body + size]))
        pos = body + size + (size & 1)  # chunk 以偶數位元組對齊
    raise WavError("bad_audio", "no data chunk")


def validate_upload(wav: WavData, *, max_seconds: float,
                    min_seconds: float = MIN_SECONDS) -> None:
    """檢查上傳錄音：16 kHz／16 bit／單聲道，且長度在範圍內。不合規丟 WavError。"""
    if wav.channels != 1 or wav.bits != 16 or wav.sample_rate != SAMPLE_RATE:
        raise WavError(
            "bad_audio",
            "need PCM 16 kHz / 16 bit / mono, got %d Hz / %d bit / %d ch"
            % (wav.sample_rate, wav.bits, wav.channels))
    if wav.frames > int(max_seconds * SAMPLE_RATE):
        raise WavError("too_long", "audio longer than %g s" % max_seconds)
    if wav.frames < int(round(min_seconds * SAMPLE_RATE)):
        raise WavError("too_short", "audio shorter than %g s" % min_seconds)


def build_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE, channels: int = 1,
              bits: int = 16) -> bytes:
    """把 PCM 樣本包成標準 44 B 標頭的 WAV（長度欄位都填正確值）。"""
    align = channels * bits // 8
    header = b"".join((
        b"RIFF", struct.pack("<I", 36 + len(pcm)), b"WAVE",
        b"fmt ", struct.pack("<IHHIIHH", 16, 1, channels, sample_rate,
                             sample_rate * align, align, bits),
        b"data", struct.pack("<I", len(pcm)),
    ))
    return header + pcm


def pcm16_samples(pcm: bytes) -> "array.array[int]":
    """little-endian PCM16 → array('h')（在大端機器上自動換位元組序）。"""
    arr = array.array("h")
    arr.frombytes(pcm[: len(pcm) // 2 * 2])
    if sys.byteorder == "big":
        arr.byteswap()
    return arr


def samples_to_pcm16(samples: "array.array[int]") -> bytes:
    """array('h') → little-endian PCM16 位元組。"""
    if sys.byteorder == "big":
        samples = array.array("h", samples)
        samples.byteswap()
    return samples.tobytes()
