# SPDX-License-Identifier: MIT
"""Configure the mmw demo over the CLI port and decode frames from the data port.

Also the shared library of the host tools: configuration parsing, serial ports and
the UART frame decoder.

Usage: uv run python host/mmw_host.py CONFIG.cfg [--frames N] [--cli PORT] [--data PORT]
"""

from __future__ import annotations

import argparse
import itertools
import math
import struct
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import serial

MAGIC = bytes([2, 1, 4, 3, 6, 5, 8, 7])
HEADER = struct.Struct("<8s8I")  # magic, version, totalPacketLen, platform, frameNumber,
#                                  timeCpuCycles, numDetectedObj, numTLVs, subFrameNumber
TLV_HEADER = struct.Struct("<2I")  # type, payload length
POINT = struct.Struct("<4f")  # x, y, z, doppler velocity
TLV_DETECTED_POINTS = 1
TLV_RANGE_DOPPLER = 5
HEATMAP_Q8_TO_DB = 20 * math.log10(2) / 2**8  # heat map values are log2 magnitude in Q8
MAX_FRAME_BYTES = 1 << 20  # well above the largest demo frame (heat maps included)
SPEED_OF_LIGHT = 299_792_458.0

CLI_PORT, CLI_BAUD, CLI_TIMEOUT_S = "/dev/ttyUSB0", 115200, 6.0
DATA_PORT, DATA_BAUD, DATA_TIMEOUT_S = "/dev/ttyUSB1", 921600, 3.0

Config = dict[str, list[list[str]]]


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


def parse_cfg(text: str) -> Config:
    """CLI command -> the arguments of each of its occurrences, comments skipped."""
    commands: Config = {}
    for line in text.splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("%"):
            commands.setdefault(fields[0], []).append(fields[1:])
    return commands


def load_cfg(path: Path) -> Config:
    return parse_cfg(path.read_text())


def cfg_args(cfg: Config, command: str) -> list[str]:
    """Arguments of the first occurrence of a command."""
    if command not in cfg:
        raise ValueError(f"configuration has no {command}")
    return cfg[command][0]


def range_axis(cfg: Config) -> tuple[int, float]:
    """Number of range bins and metres per bin, from profileCfg."""
    profile = cfg_args(cfg, "profileCfg")
    slope_hz_per_s = float(profile[7]) * 1e12
    num_samples = int(profile[9])
    sample_rate_hz = float(profile[10]) * 1e3
    num_bins = 1 << (num_samples - 1).bit_length()
    return num_bins, SPEED_OF_LIGHT * sample_rate_hz / (2 * slope_hz_per_s * num_bins)


def ddm_params(cfg: Config) -> tuple[int, int]:
    """(Doppler sub-bands, TX antennas per chirp) from ddmCfg and the first chirpCfg;
    0 sub-bands means TDM."""
    bands = int(cfg["ddmCfg"][0][0]) if "ddmCfg" in cfg else 0
    return bands, int(cfg_args(cfg, "chirpCfg")[7]).bit_count()


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


def add_port_args(parser: argparse.ArgumentParser, data: bool = True) -> None:
    parser.add_argument("--cli", default=CLI_PORT, help=f"CLI port (default {CLI_PORT})")
    if data:
        parser.add_argument("--data", default=DATA_PORT, help=f"data port (default {DATA_PORT})")


@contextmanager
def running_radar(cfg: Path, cli_port: str, data_port: str) -> Iterator[serial.Serial]:
    """Configure and start the radar; yields the data port and stops the radar on exit."""
    with serial.Serial(cli_port, CLI_BAUD, timeout=CLI_TIMEOUT_S) as cli, \
         serial.Serial(data_port, DATA_BAUD, timeout=DATA_TIMEOUT_S) as data:
        send_config(cli, cfg)
        data.reset_input_buffer()
        try:
            yield data
        finally:
            cli.write(b"sensorStop\n")


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
    """Frames from the data port, skipping corrupted ones with a message on stderr."""
    while True:
        try:
            yield read_frame(data)
        except FrameError as err:
            print(f"skipped corrupted frame: {err}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--frames", type=int, default=10)
    add_port_args(parser)
    args = parser.parse_args()

    with running_radar(args.config, args.cli, args.data) as data:
        for frame in itertools.islice(frames(data), args.frames):
            nearest = min(frame.points, key=lambda p: p.x**2 + p.y**2, default=None)
            summary = (f"nearest ({nearest.x:+.2f}, {nearest.y:+.2f}, {nearest.z:+.2f}) m, "
                       f"v={nearest.v:+.2f} m/s") if nearest else "no points"
            print(f"frame {frame.number:5d}: {len(frame.points):3d} points, {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
