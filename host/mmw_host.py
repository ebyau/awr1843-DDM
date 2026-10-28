# SPDX-License-Identifier: MIT
"""Configure the mmw demo over the CLI port and decode frames from the data port.

Usage: uv run python host/mmw_host.py CONFIG.cfg [--frames N] [--cli PORT] [--data PORT]
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import serial

MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])
HEADER = struct.Struct("<8s8I")  # magic, version, totalPacketLen, platform, frameNumber,
#                                  timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
TLV_HEADER = struct.Struct("<2I")  # type, payload length
POINT = struct.Struct("<4f")  # x, y, z, doppler velocity
TLV_DETECTED_POINTS = 1
MAX_FRAME_BYTES = 1 << 20  # well above the largest demo frame (heat maps included)
SPEED_OF_LIGHT = 3e8


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


def range_axis(cfg: Path) -> tuple[int, float]:
    """Number of range bins and metres per bin, from the configuration's profileCfg."""
    for line in cfg.read_text().splitlines():
        fields = line.split()
        if fields and fields[0] == "profileCfg":
            slope_hz_per_s = float(fields[8]) * 1e12
            num_samples = int(fields[10])
            sample_rate_hz = float(fields[11]) * 1e3
            num_bins = 1 << (num_samples - 1).bit_length()
            return num_bins, SPEED_OF_LIGHT * sample_rate_hz / (2 * slope_hz_per_s * num_bins)
    raise ValueError(f"no profileCfg in {cfg}")


def send_config(cli: serial.Serial, cfg: Path) -> None:
    """Send each command line and fail fast on any reply other than 'Done'."""
    for line in cfg.read_text().splitlines():
        cmd = line.strip()
        if not cmd or cmd.startswith("%"):
            continue
        cli.write(f"{cmd}\n".encode())
        reply = cli.read_until(b"mmwDemo:/>").decode(errors="replace")
        if "Done" not in reply and cmd != "sensorStop":
            raise RuntimeError(f"'{cmd}' failed:\n{reply.strip()}")
        time.sleep(0.01)


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--cli", default="/dev/ttyUSB0")
    parser.add_argument("--data", default="/dev/ttyUSB1")
    args = parser.parse_args()

    with serial.Serial(args.cli, 115200, timeout=6) as cli, \
         serial.Serial(args.data, 921600, timeout=2) as data:
        send_config(cli, args.config)
        data.reset_input_buffer()
        try:
            for _ in range(args.frames):
                try:
                    frame = read_frame(data)
                except FrameError as err:
                    print(f"skipped corrupted frame: {err}", file=sys.stderr)
                    continue
                nearest = min(frame.points, key=lambda p: p.x**2 + p.y**2, default=None)
                summary = (f"nearest ({nearest.x:+.2f}, {nearest.y:+.2f}, {nearest.z:+.2f}) m, "
                           f"v={nearest.v:+.2f} m/s") if nearest else "no points"
                print(f"frame {frame.number:5d}: {len(frame.points):3d} points, {summary}")
        finally:
            cli.write(b"sensorStop\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
