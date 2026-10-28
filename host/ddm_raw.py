# SPDX-License-Identifier: MIT
"""Decode raw DDM frames captured with raw_capture.py.

Computes the range-Doppler map from the ADC samples, finds the strongest targets
on the sub-band-folded map (as the firmware does), and prints for each the TX0
sub-band, the unambiguous velocity and the level of every sub-band, so the TX
copies and the empty sub-band can be checked independently of the firmware.

The sub-band and TX counts come from the configuration saved with the capture.

Usage: uv run python host/ddm_raw.py capture.npz [--snapshot out.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from mmw_host import SPEED_OF_LIGHT, Config, cfg_args, ddm_params, parse_cfg, range_axis
from plotting import draw_axes

# Host-side peak picking, a simpler statistic than the firmware's CFAR: changing
# cfarCfg does not change it.
DETECTION_DB = 15.0  # above the median of the folded map
MAX_TARGETS = 10


def chirp_axes(cfg: Config, num_chirps: int) -> tuple[float, float]:
    """Metres per range bin and m/s per Doppler bin when every chirp is sampled."""
    profile = [float(f) for f in cfg_args(cfg, "profileCfg")[:11]]
    start_ghz, idle_us, adc_start_us, ramp_end_us = profile[1:5]
    slope_mhz_us, samples, rate_ksps = profile[7], profile[9], profile[10]
    sample_time_us = samples / (rate_ksps / 1e3)
    centre_hz = (start_ghz * 1e3 + slope_mhz_us * (adc_start_us + sample_time_us / 2)) * 1e6
    velocity_step = SPEED_OF_LIGHT / (2 * centre_hz * num_chirps * (idle_us + ramp_end_us) * 1e-6)
    return range_axis(cfg)[1], velocity_step


def min_range_m(cfg: Config) -> float:
    """Near edge of the firmware's CFAR range window (cfarFovCfg ... 0 min max), which
    also skips TX-to-RX leakage; 0 without one."""
    windows = [args for args in cfg.get("cfarFovCfg", []) if args[1] == "0"]
    return float(windows[0][2]) if windows else 0.0


def doppler_spectrum(frames: np.ndarray) -> np.ndarray:
    """[..., chirp, rx, sample] -> complex [..., Doppler, rx, range] (Hann windows)."""
    num_chirps, num_samples = frames.shape[-3], frames.shape[-1]
    spectrum = np.fft.fft(frames * np.hanning(num_samples), axis=-1)
    return np.fft.fft(spectrum * np.hanning(num_chirps)[:, None, None], axis=-3)


def range_doppler_power(frames: np.ndarray) -> np.ndarray:
    """[frame, chirp, rx, sample] -> power [range, Doppler], summed over RX, mean over frames."""
    return (np.abs(doppler_spectrum(frames)) ** 2).sum(axis=2).mean(axis=0).T


def remove_static(frames: np.ndarray, chirps_per_loop: int) -> np.ndarray:
    """Subtracts each chirp slot's mean over the loops of a frame [..., chirp, rx, sample].

    This removes the Doppler bins that are multiples of the number of loops. With DDM
    (one chirp per sub-band in a loop) those hold every TX copy of a static target.
    """
    shape = frames.shape
    slots = frames.reshape(*shape[:-3], shape[-3] // chirps_per_loop, chirps_per_loop, *shape[-2:])
    return (slots - slots.mean(axis=-4, keepdims=True)).reshape(shape)


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


def tx0_band(band_power: np.ndarray, num_tx: int) -> np.ndarray:
    """First band of the strongest run of num_tx cyclically consecutive bands (axis 0)."""
    runs = sum(np.roll(band_power, -k, axis=0) for k in range(num_tx))
    return np.argmax(runs, axis=0)


def ddm_virtual_array(spectrum: np.ndarray, bands: int, num_tx: int) -> tuple[np.ndarray, np.ndarray]:
    """Separates the TX copies of every cell of one frame's spectrum [Doppler, rx, range].

    Returns the virtual array [folded bin, range, tx, rx] and TX0's unfolded Doppler bin
    [folded bin, range].
    """
    num_doppler, _, num_range = spectrum.shape
    width = num_doppler // bands
    power = (np.abs(spectrum) ** 2).sum(axis=1).reshape(bands, width, num_range)
    tx0 = tx0_band(power, num_tx)
    folded = np.arange(width)[:, None]
    by_range = spectrum.transpose(0, 2, 1)  # [Doppler, range, rx]
    cells = np.arange(num_range)
    virtual = np.stack([by_range[folded + width * ((tx0 + k) % bands), cells]
                        for k in range(num_tx)], axis=2)
    return virtual, folded + width * tx0


def signed_doppler_bin(folded_bin: int, tx0: int, width: int, num_chirps: int) -> int:
    """TX0's Doppler bin, -num_chirps/2 .. num_chirps/2-1."""
    doppler_bin = folded_bin + width * tx0
    return doppler_bin - num_chirps if doppler_bin >= num_chirps // 2 else doppler_bin


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture", type=Path)
    parser.add_argument("--snapshot", type=Path, help="save the range-Doppler map to this PNG")
    args = parser.parse_args()

    data = np.load(args.capture)
    frames, cfg = data["frames"], parse_cfg(str(data["config"]))
    bands, num_tx = ddm_params(cfg)
    if bands <= num_tx:
        raise ValueError("the capture's configuration is not DDM (ddmCfg with more bands than TX)")
    num_chirps = frames.shape[1]
    width = num_chirps // bands
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    power = range_doppler_power(frames)

    print(f"{len(frames)} frames; {range_step:.3f} m and {velocity_step:.3f} m/s per bin")
    print(" range(m)  v(m/s)  TX0  " + "  ".join(f"band{b}(dB)" for b in range(bands))
          + "  weakest TX - mean spare (dB)")
    min_range_bin = int(np.ceil(min_range_m(cfg) / range_step))
    for range_bin, folded_bin in find_targets(fold(power, bands), min_range_bin):
        band_power = power[range_bin, folded_bin::width]
        tx0 = int(tx0_band(band_power, num_tx))
        tx_bands = [(tx0 + k) % bands for k in range(num_tx)]
        spare = np.delete(band_power, tx_bands)
        margin_db = 10 * np.log10(band_power[tx_bands].min() / spare.mean())
        signed_bin = signed_doppler_bin(folded_bin, tx0, width, num_chirps)
        levels = 10 * np.log10(band_power / band_power.max())
        print(f"{range_bin * range_step:9.2f} {signed_bin * velocity_step:7.2f} {tx0:4d}  "
              + "  ".join(f"{level:10.1f}" for level in levels) + f"  {margin_db:28.1f}")

    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    db = 10 * np.log10(power / power.max())
    image = draw_axes(ax, db, range_step, bands, f"Raw-data range-Doppler map, {len(frames)} frames")
    fig.colorbar(image, ax=ax, label="Level relative to peak (dB)", shrink=0.8)
    if args.snapshot is not None:
        fig.savefig(args.snapshot, dpi=120)
        print(f"Saved {args.snapshot}")
    else:
        plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
