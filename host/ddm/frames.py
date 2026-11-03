# SPDX-License-Identifier: MIT
"""Decoder for the mmw demo's UART output: frames of type-length-value (TLV) records."""

from __future__ import annotations

import logging
import math
import struct
from collections.abc import Iterator
from dataclasses import dataclass

import serial

log = logging.getLogger(__name__)

MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])
HEADER = struct.Struct("<8s8I")  # magic, version, totalPacketLen, platform, frameNumber,
#                                  timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
TLV_HEADER = struct.Struct("<2I")  # type, payload length
POINT = struct.Struct("<4f")  # x, y, z, doppler velocity
TLV_DETECTED_POINTS = 1
TLV_RANGE_DOPPLER = 5
HEATMAP_Q8_TO_DB = 20 * math.log10(2) / 2**8  # heat map values are log2 magnitude in Q8
MAX_FRAME_BYTES = 1 << 20  # well above the largest demo frame (heat maps included)


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float
    v: float


@dataclass(frozen=True)
class Frame:
    number: int
    tlvs: dict[int, bytes]

    @property
    def points(self) -> list[Point]:
        payload = self.tlvs.get(TLV_DETECTED_POINTS, b"")
        return [Point(*p) for p in POINT.iter_unpack(payload)]


class FrameError(ValueError):
    """A frame whose lengths are inconsistent, usually because UART bytes were dropped."""


def read_frame(data: serial.Serial) -> Frame:
    """Block until one complete frame is received and return its TLV payloads.

    Raises FrameError for a corrupted frame; the next call resynchronises on the
    following magic word.
    """
    buf = data.read_until(MAGIC)
    if not buf.endswith(MAGIC):
        raise TimeoutError("no frame received on data port")
    rest = data.read(HEADER.size - len(MAGIC))
    if len(rest) != HEADER.size - len(MAGIC):
        raise TimeoutError("truncated frame header")
    _, _, total_len, _, frame_no, _, _, num_tlvs, _ = HEADER.unpack(MAGIC + rest)
    if not HEADER.size <= total_len <= MAX_FRAME_BYTES:
        raise FrameError(f"frame length {total_len} out of range")
    body = data.read(total_len - HEADER.size)
    if len(body) != total_len - HEADER.size:
        raise TimeoutError("truncated frame")
    if MAGIC in body:
        raise FrameError(f"frame {frame_no}: next frame starts inside this one; bytes were dropped")

    tlvs: dict[int, bytes] = {}
    offset = 0
    for _ in range(num_tlvs):
        if offset + TLV_HEADER.size > len(body):
            raise FrameError(f"frame {frame_no}: TLV header past end of frame")
        tlv_type, length = TLV_HEADER.unpack_from(body, offset)
        offset += TLV_HEADER.size
        if offset + length > len(body):
            raise FrameError(f"frame {frame_no}: TLV {tlv_type} length {length} past end of frame")
        tlvs[tlv_type] = body[offset:offset + length]
        offset += length
    return Frame(frame_no, tlvs)


def frames(data: serial.Serial) -> Iterator[Frame]:
    """Frames from the data port, skipping (and logging) corrupted ones."""
    while True:
        try:
            yield read_frame(data)
        except FrameError as err:
            log.warning("skipped corrupted frame: %s", err)
