# SPDX-License-Identifier: MIT
"""Decode raw DDM frames captured with raw_capture.py.

Computes the range-Doppler map from the ADC samples, finds the strongest targets
on the sub-band-folded map (as the firmware does), and prints for each the TX0
sub-band, the unambiguous velocity and the level of every sub-band, so the TX
copies and the empty sub-band can be checked independently of the firmware.

Usage: uv run python host/ddm_raw.py capture.npz [--bands 4] [--tx 3] [--snapshot out.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from mmw_host import SPEED_OF_LIGHT
from raw_capture import parse_cfg
from rd_view import INK, draw_axes

DETECTION_DB = 15.0  # above the median of the folded map
MIN_RANGE_M = 0.25  # skips TX-to-RX leakage, like the firmware's CFAR range window
MAX_TARGETS = 10


def chirp_axes(cfg: dict[str, list[str]], num_chirps: int) -> tuple[float, float]:
    """Metres per range bin and m/s per Doppler bin when every chirp is sampled."""
    _, start_ghz, idle_us, adc_start_us, ramp_end_us, _, _, slope_mhz_us, _, samples, rate_ksps = (
        float(f) for f in cfg["profileCfg"][:11])
    sample_time_us = samples / (rate_ksps / 1e3)
    centre_hz = (start_ghz * 1e3 + slope_mhz_us * (adc_start_us + sample_time_us / 2)) * 1e6
    range_step = SPEED_OF_LIGHT * rate_ksps * 1e3 / (2 * slope_mhz_us * 1e12 * samples)
    velocity_step = SPEED_OF_LIGHT / (2 * centre_hz * num_chirps * (idle_us + ramp_end_us) * 1e-6)
    return range_step, velocity_step


def range_doppler_power(frames: np.ndarray) -> np.ndarray:
    """[frame, chirp, rx, sample] -> power [range, Doppler], summed over RX, mean over frames."""
    num_chirps, num_samples = frames.shape[1], frames.shape[3]
    spectrum = np.fft.fft(frames * np.hanning(num_samples), axis=3)
    spectrum = np.fft.fft(spectrum * np.hanning(num_chirps)[:, None, None], axis=1)
    return (np.abs(spectrum) ** 2).sum(axis=2).mean(axis=0).T


def fold(power: np.ndarray, bands: int) -> np.ndarray:
    """Mean log-power over the sub-bands, as the firmware's detection matrix: [range, bin]."""
    num_range, num_doppler = power.shape
    return np.log10(power).reshape(num_range, bands, num_doppler // bands).mean(axis=1) * 10


def find_targets(folded_db: np.ndarray, min_range_bin: int = 0) -> list[tuple[int, int]]:
    """Strongest local maxima of the folded map at or beyond min_range_bin that clear the
    detection threshold."""
    padded = np.pad(folded_db, ((1, 1), (0, 0)), constant_values=-np.inf)
    is_peak = np.ones(folded_db.shape, dtype=bool)
    for dr in (-1, 0, 1):
        for dd in (-1, 0, 1):
            if dr or dd:
                neighbour = np.roll(padded, (dr, dd), axis=(0, 1))[1:-1]
                is_peak &= folded_db >= neighbour
    is_peak &= folded_db > np.median(folded_db) + DETECTION_DB
    is_peak[:min_range_bin] = False
    cells = np.argwhere(is_peak)
    order = np.argsort(folded_db[is_peak])[::-1][:MAX_TARGETS]
    return [tuple(cells[i]) for i in order]


def tx0_band(band_power: np.ndarray, num_tx: int) -> int:
    """First band of the strongest run of num_tx cyclically consecutive bands."""
    runs = sum(np.roll(band_power, -k) for k in range(num_tx))
    return int(np.argmax(runs))


def signed_doppler_bin(folded_bin: int, tx0: int, width: int, num_chirps: int) -> int:
    """TX0's Doppler bin, -num_chirps/2 .. num_chirps/2-1."""
    doppler_bin = folded_bin + width * tx0
    return doppler_bin - num_chirps if doppler_bin >= num_chirps // 2 else doppler_bin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=Path)
    parser.add_argument("--bands", type=int, default=4)
    parser.add_argument("--tx", type=int, default=3)
    parser.add_argument("--snapshot", type=Path, help="save the range-Doppler map to this PNG")
    args = parser.parse_args()

    data = np.load(args.capture)
    frames, cfg = data["frames"], parse_cfg(str(data["config"]))
    num_chirps = frames.shape[1]
    width = num_chirps // args.bands
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    power = range_doppler_power(frames)

    print(f"{len(frames)} frames; {range_step:.3f} m and {velocity_step:.3f} m/s per bin")
    print(" range(m)  v(m/s)  TX0  " + "  ".join(f"band{b}(dB)" for b in range(args.bands))
          + "  weakest TX - mean spare (dB)")
    min_range_bin = int(np.ceil(MIN_RANGE_M / range_step))
    for range_bin, folded_bin in find_targets(fold(power, args.bands), min_range_bin):
        band_power = power[range_bin, folded_bin::width]
        tx0 = tx0_band(band_power, args.tx)
        tx_bands = [(tx0 + k) % args.bands for k in range(args.tx)]
        spare = np.delete(band_power, tx_bands)
        margin_db = 10 * np.log10(band_power[tx_bands].min() / spare.mean())
        signed_bin = signed_doppler_bin(folded_bin, tx0, width, num_chirps)
        levels = 10 * np.log10(band_power / band_power.max())
        print(f"{range_bin * range_step:9.2f} {signed_bin * velocity_step:7.2f} {tx0:4d}  "
              + "  ".join(f"{level:10.1f}" for level in levels) + f"  {margin_db:28.1f}")

    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    db = 10 * np.log10(power / power.max())
    image = draw_axes(ax, db, range_step, args.bands)
    fig.colorbar(image, ax=ax, label="Level relative to peak (dB)", shrink=0.8)
    ax.set_title(f"Raw-data range-Doppler map, {len(frames)} frames", color=INK, loc="left")
    if args.snapshot is not None:
        fig.savefig(args.snapshot, dpi=120)
        print(f"Saved {args.snapshot}")
    else:
        plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
