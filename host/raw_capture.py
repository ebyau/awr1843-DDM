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

from mmw_host import CLI_BAUD, CLI_TIMEOUT_S, Config, add_port_args, cfg_args, load_cfg, send_config

CAPTURE_TIMEOUT_S = 3.0  # the stream ends when no data arrives for this long


def chirps_per_loop(cfg: Config) -> int:
    chirp_start, chirp_end = (int(f) for f in cfg_args(cfg, "frameCfg")[:2])
    return chirp_end - chirp_start + 1


def raw_frame_shape(cfg: Config) -> tuple[int, int, int]:
    """(chirps, rx, samples) of one raw frame; every chirp carries all enabled RX."""
    if cfg_args(cfg, "adcCfg")[1] == "0":
        raise ValueError("raw capture needs complex ADC output (adcCfg 2 1)")
    if cfg_args(cfg, "lvdsStreamCfg")[1:4] != ["0", "1", "0"]:
        raise ValueError("raw capture needs headerless ADC data on LVDS (lvdsStreamCfg -1 0 1 0)")
    loops = int(cfg_args(cfg, "frameCfg")[2])
    num_rx = int(cfg_args(cfg, "channelCfg")[0]).bit_count()
    return chirps_per_loop(cfg) * loops, num_rx, int(cfg_args(cfg, "profileCfg")[9])


def open_capture_card() -> DCA1000EVM:
    """Capture card at xwr's default addresses (PC 192.168.33.30, card 192.168.33.180)."""
    return DCAConfig(timeout=CAPTURE_TIMEOUT_S).create()


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
    shape = raw_frame_shape(load_cfg(cfg_path))
    with serial.Serial(cli_port, CLI_BAUD, timeout=CLI_TIMEOUT_S) as cli:
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
    add_port_args(parser, data=False)
    args = parser.parse_args()

    stream = capture(args.config, args.cli, open_capture_card())
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
