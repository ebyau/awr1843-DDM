"""Check DDM sub-band separation in the range-Doppler heatmap.

Runs a DDM config, then, for the strongest range bin, reports the energy in each
Doppler sub-band. With DDM working, the TX bands hold the target and the last
band is empty (tens of dB lower).

Usage: python3 ddm_check.py CONFIG.cfg [--bands 4] [--frames 5]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import serial

from mmw_host import read_frame, send_config

TLV_RANGE_DOPPLER = 5
LOG2_TO_DB = 20 * np.log10(2) / 2**8  # heatmap values are log2 magnitude in Q8


def band_levels_db(heatmap: np.ndarray, bands: int) -> np.ndarray:
    """Peak level per Doppler sub-band at the strongest range bin, in dB."""
    row = heatmap[np.argmax(heatmap.max(axis=1))]
    return row.reshape(bands, -1).max(axis=1) * LOG2_TO_DB


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--bands", type=int, default=4)
    parser.add_argument("--frames", type=int, default=5)
    parser.add_argument("--range-bins", type=int, default=256)
    parser.add_argument("--cli", default="/dev/ttyUSB0")
    parser.add_argument("--data", default="/dev/ttyUSB1")
    args = parser.parse_args()

    with serial.Serial(args.cli, 115200, timeout=6) as cli, \
         serial.Serial(args.data, 921600, timeout=3) as data:
        send_config(cli, args.config)
        data.reset_input_buffer()
        try:
            for _ in range(args.frames):
                frame = read_frame(data)
                raw = frame.tlvs.get(TLV_RANGE_DOPPLER)
                if raw is None:
                    print(f"frame {frame.number}: no range-Doppler heatmap TLV")
                    continue
                heatmap = np.frombuffer(raw, dtype="<u2").reshape(args.range_bins, -1)
                levels = band_levels_db(heatmap.astype(float), args.bands)
                rel = levels - levels.max()
                bands = "  ".join(f"band{i}: {r:6.1f} dB" for i, r in enumerate(rel))
                print(f"frame {frame.number:4d} ({heatmap.shape[1]} Doppler bins): {bands}")
        finally:
            cli.write(b"sensorStop\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
