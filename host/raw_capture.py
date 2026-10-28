# SPDX-License-Identifier: MIT
"""Capture raw ADC frames from the radar through a DCA1000EVM capture card.

The configuration must stream ADC samples over LVDS (lvdsStreamCfg -1 0 1 0) with
complex 16-bit samples. The capture card is driven by xwr (github.com/RadarML/xwr);
the radar is configured from the .cfg file, so DDM and TDM configurations both work.
Frames are saved as complex samples [frame, chirp, rx, sample] with the configuration.

Usage: uv run python host/raw_capture.py CONFIG.cfg [--frames 50] [--out capture.npz]
"""

from __future__ import annotations

import argparse
import itertools
import sys
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import serial
from xwr import DCAConfig
from xwr.capture import DCA1000EVM

from mmw_host import send_config


def parse_cfg(text: str) -> dict[str, list[str]]:
    """CLI command -> arguments of its last occurrence, comments skipped."""
    commands: dict[str, list[str]] = {}
    for line in text.splitlines():
        fields = line.split()
        if fields and not fields[0].startswith("%"):
            commands[fields[0]] = fields[1:]
    return commands


def raw_frame_shape(cfg: dict[str, list[str]]) -> tuple[int, int, int]:
    """(chirps, rx, samples) of one raw frame; every chirp carries all enabled RX."""
    if cfg["adcCfg"][1] == "0":
        raise ValueError("raw capture needs complex ADC output (adcCfg 2 1)")
    if cfg["lvdsStreamCfg"][1:4] != ["0", "1", "0"]:
        raise ValueError("raw capture needs headerless ADC data on LVDS (lvdsStreamCfg -1 0 1 0)")
    chirp_start, chirp_end, loops = (int(f) for f in cfg["frameCfg"][:3])
    num_rx = int(cfg["channelCfg"][0]).bit_count()
    return (chirp_end - chirp_start + 1) * loops, num_rx, int(cfg["profileCfg"][9])


def iiqq_to_complex(data: bytes | bytearray, shape: tuple[int, int, int]) -> np.ndarray:
    """Capture-card byte stream -> complex64 [chirp, rx, sample].

    Two LVDS lanes carry alternate samples, Q before I, and the card interleaves
    them as Q0 Q1 I0 I1 Q2 Q3 I2 I3 ...
    """
    iiqq = np.frombuffer(data, dtype="<i2").reshape(*shape[:-1], 2 * shape[-1]).astype(np.float32)
    iq = np.empty(shape, dtype=np.complex64)
    iq[..., 0::2] = iiqq[..., 2::4] + 1j * iiqq[..., 0::4]
    iq[..., 1::2] = iiqq[..., 3::4] + 1j * iiqq[..., 1::4]
    return iq


def capture(cfg_path: Path, cli_port: str, dca: DCA1000EVM) -> Iterator[np.ndarray]:
    """Configure and start the radar, then yield complete raw frames until closed.

    The capture card starts after the radar stops and before it restarts, so that
    its byte count, which sets the frame boundaries, starts at the first chirp.
    """
    shape = raw_frame_shape(parse_cfg(cfg_path.read_text()))
    with serial.Serial(cli_port, 115200, timeout=6) as cli:
        cli.write(b"sensorStop\n")
        cli.read_until(b"mmwDemo:/>")
        dca.stop()
        dca.flush()
        dca.start()
        try:
            send_config(cli, cfg_path)
            for frame in dca.stream([*shape[:-1], 2 * shape[-1]]):
                if frame.complete:
                    yield iiqq_to_complex(frame.data, shape)
                else:
                    print("skipped incomplete frame", file=sys.stderr)
        finally:
            cli.write(b"sensorStop\n")
            dca.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--frames", type=int, default=50)
    parser.add_argument("--out", type=Path, default=Path("capture.npz"))
    parser.add_argument("--cli", default="/dev/ttyUSB0")
    args = parser.parse_args()

    dca = DCAConfig(timeout=3.0).create()
    stream = capture(args.config, args.cli, dca)
    try:
        frames = list(itertools.islice(stream, args.frames))
    finally:
        stream.close()
    if not frames:
        raise TimeoutError("no frames received; check the LVDS cable and capture card")
    if len(frames) < args.frames:
        print(f"stream timed out after {len(frames)} of {args.frames} frames", file=sys.stderr)
    np.savez_compressed(args.out, frames=np.stack(frames), config=args.config.read_text())
    print(f"Saved {len(frames)} frames of {frames[0].shape} (chirp, rx, sample) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
