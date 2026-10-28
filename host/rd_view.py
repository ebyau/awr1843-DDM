"""Live range-Doppler heat map from the mmw demo.

Shows the unfolded Doppler spectrum with the DDM sub-band boundaries marked, so
each target's TX copies and the empty sub-band are visible. The configuration
must enable the range-Doppler heat map (guiMonitor ... 1 ...).

Usage: python3 rd_view.py CONFIG.cfg [--bands 4] [--snapshot out.png]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import serial
from matplotlib.axes import Axes
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.image import AxesImage

from mmw_host import read_frame, send_config

TLV_RANGE_DOPPLER = 5
SPEED_OF_LIGHT = 3e8
Q8_TO_DB = 20 * np.log10(2) / 2**8  # heat map values are log2 magnitude in Q8
DYNAMIC_RANGE_DB = 40.0

# Sequential blue ramp, light (weak) to dark (strong).
CMAP = LinearSegmentedColormap.from_list(
    "seq_blue", ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
INK = "#1f2933"
MUTED = "#6b7785"


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


def to_db(raw: bytes, num_range_bins: int) -> np.ndarray:
    """Heat map payload -> [range, Doppler] array in dB relative to its peak."""
    heatmap = np.frombuffer(raw, dtype="<u2").reshape(num_range_bins, -1) * Q8_TO_DB
    return heatmap - heatmap.max()


def centre_bands(db: np.ndarray, bands: int) -> np.ndarray:
    """Rotate the Doppler axis by half a sub-band so zero velocity sits mid-band."""
    return np.roll(db, db.shape[1] // max(bands, 1) // 2, axis=1) if bands > 0 else db


def draw_axes(ax: Axes, db: np.ndarray, range_step: float, bands: int) -> AxesImage:
    """Heat map with Doppler bins on x, range on y, and sub-band boundaries marked.

    With sub-bands, the Doppler axis starts half a sub-band below bin 0, so each
    copy of a static target sits in the middle of its sub-band.
    """
    num_range, num_doppler = db.shape
    width = num_doppler // bands if bands > 0 else num_doppler
    shift = width // 2 if bands > 0 else 0
    image = ax.imshow(centre_bands(db, bands), cmap=CMAP, vmin=-DYNAMIC_RANGE_DB, vmax=0,
                      aspect="auto", origin="lower", interpolation="nearest",
                      extent=(-shift - 0.5, num_doppler - shift - 0.5, 0, num_range * range_step))
    ax.set_xlabel("Doppler bin (unfolded; negative bins wrap from the top)", color=MUTED)
    ax.set_ylabel("Range (m)", color=MUTED)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_visible(False)

    if bands > 0:
        for band in range(1, bands):
            ax.axvline(band * width - shift - 0.5, color=INK, linewidth=1, linestyle=(0, (4, 3)))
        top = ax.secondary_xaxis("top")
        top.set_xticks([b * width for b in range(bands)],
                       [f"sub-band {b}" for b in range(bands)], color=MUTED)
        top.tick_params(length=0)
        for spine in top.spines.values():
            spine.set_visible(False)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--bands", type=int, default=4, help="DDM sub-bands (0: no markers)")
    parser.add_argument("--snapshot", type=Path, help="save one frame to this PNG and exit")
    parser.add_argument("--cli", default="/dev/ttyUSB0")
    parser.add_argument("--data", default="/dev/ttyUSB1")
    args = parser.parse_args()

    num_range_bins, range_step = range_axis(args.config)
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    image: AxesImage | None = None

    with serial.Serial(args.cli, 115200, timeout=6) as cli, \
         serial.Serial(args.data, 921600, timeout=3) as data:
        send_config(cli, args.config)
        data.reset_input_buffer()
        try:
            while True:
                frame = read_frame(data)
                raw = frame.tlvs.get(TLV_RANGE_DOPPLER)
                if raw is None:
                    raise RuntimeError("frame has no range-Doppler heat map; enable it in guiMonitor")
                db = to_db(raw, num_range_bins)
                if image is None:
                    image = draw_axes(ax, db, range_step, args.bands)
                    fig.colorbar(image, ax=ax, label="Level relative to peak (dB)", shrink=0.8)
                else:
                    image.set_data(centre_bands(db, args.bands))
                ax.set_title(f"Range-Doppler map, frame {frame.number}", color=INK, loc="left")
                if args.snapshot is not None:
                    fig.savefig(args.snapshot, dpi=120)
                    print(f"Saved {args.snapshot}")
                    break
                plt.pause(0.01)
                if not plt.fignum_exists(fig.number):
                    break
        finally:
            cli.write(b"sensorStop\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
