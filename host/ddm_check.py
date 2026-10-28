# SPDX-License-Identifier: MIT
"""Check DDM sub-band separation in the range-Doppler heatmap.

Runs a DDM config, then, for the strongest range bin, reports the energy in each
Doppler sub-band, centred on the copies of static targets (use a static scene). With
DDM working, the TX bands hold the target and the last band is empty (tens of dB lower).

Usage: uv run python host/ddm_check.py CONFIG.cfg [--bands N] [--frames 5]
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np

from mmw_host import (
    HEATMAP_Q8_TO_DB,
    TLV_RANGE_DOPPLER,
    add_port_args,
    ddm_params,
    frames,
    load_cfg,
    range_axis,
    running_radar,
)
from plotting import centre_bands


def band_levels_db(heatmap: np.ndarray, bands: int) -> np.ndarray:
    """Peak level per Doppler sub-band at the strongest range bin, in dB.

    The sub-bands are centred on their static-target copies, as in the plots: a
    static target sits on a band edge, so its Doppler spill would otherwise count
    as the neighbouring (empty) band.
    """
    row = heatmap[np.argmax(heatmap.max(axis=1))]
    return centre_bands(row[None, :], bands)[0].reshape(bands, -1).max(axis=1) * HEATMAP_Q8_TO_DB


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--bands", type=int, help="sub-bands (default: ddmCfg)")
    parser.add_argument("--frames", type=int, default=5)
    add_port_args(parser)
    args = parser.parse_args()

    cfg = load_cfg(args.config)
    num_range_bins, _ = range_axis(cfg)
    bands = ddm_params(cfg)[0] if args.bands is None else args.bands
    if bands < 2:
        raise ValueError("the configuration has no ddmCfg; pass --bands")

    with running_radar(args.config, args.cli, args.data) as data:
        for frame in itertools.islice(frames(data), args.frames):
            raw = frame.tlvs.get(TLV_RANGE_DOPPLER)
            if raw is None:
                print(f"frame {frame.number}: no range-Doppler heatmap TLV")
                continue
            heatmap = np.frombuffer(raw, dtype="<u2").reshape(num_range_bins, -1)
            levels = band_levels_db(heatmap.astype(float), bands)
            rel = levels - levels.max()
            text = "  ".join(f"band{i}: {r:6.1f} dB" for i, r in enumerate(rel))
            print(f"frame {frame.number:4d} ({heatmap.shape[1]} Doppler bins): {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
