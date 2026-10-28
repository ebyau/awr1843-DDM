# SPDX-License-Identifier: MIT
"""Live range-Doppler heat map from the mmw demo.

Shows the unfolded Doppler spectrum with the DDM sub-band boundaries marked, so
each target's TX copies and the empty sub-band are visible. The configuration
must enable the range-Doppler heat map (guiMonitor ... 1 ...).

Usage: uv run python host/rd_view.py CONFIG.cfg [--bands 4] [--snapshot out.png]
"""

from __future__ import annotations

import argparse
import contextlib
import queue
import sys
import threading
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import serial
from matplotlib.axes import Axes
from matplotlib.image import AxesImage

from mmw_host import Frame, FrameError, range_axis, read_frame, send_config

TLV_RANGE_DOPPLER = 5
SNAPSHOT_TIMEOUT_S = 15.0
Q8_TO_DB = 20 * np.log10(2) / 2**8  # heat map values are log2 magnitude in Q8
DYNAMIC_RANGE_DB = 40.0

CMAP = "viridis"  # perceptually uniform, dark (weak) to yellow (strong); as in the xwr demo
INK = "#1f2933"
MUTED = "#6b7785"


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
                      extent=(-shift - 0.5, num_doppler - shift - 0.5,
                              -range_step / 2, (num_range - 0.5) * range_step))
    ax.set_xlabel("Doppler bin (unfolded; negative bins wrap from the top)", color=MUTED)
    ax.set_ylabel("Range (m)", color=MUTED)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_visible(False)

    if bands > 0:
        for band in range(1, bands):
            ax.axvline(band * width - shift - 0.5, color="white", alpha=0.7, linewidth=1,
                       linestyle=(0, (4, 3)))
        top = ax.secondary_xaxis("top")
        top.set_xticks([b * width for b in range(bands)],
                       [f"sub-band {b}" for b in range(bands)], color=MUTED)
        top.tick_params(length=0)
        for spine in top.spines.values():
            spine.set_visible(False)
    return image


def read_frames(data: serial.Serial, latest: queue.Queue[Frame], stop: threading.Event) -> None:
    """Read frames continuously, keeping only the newest, so the UART never overflows
    while the plot redraws."""
    while not stop.is_set():
        try:
            frame = read_frame(data)
        except FrameError as err:
            print(f"skipped corrupted frame: {err}", file=sys.stderr)
            continue
        except TimeoutError:
            continue
        with contextlib.suppress(queue.Empty):
            latest.get_nowait()
        latest.put(frame)


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
    latest: queue.Queue[Frame] = queue.Queue(maxsize=1)
    stop = threading.Event()

    with serial.Serial(args.cli, 115200, timeout=6) as cli, \
         serial.Serial(args.data, 921600, timeout=3) as data:
        send_config(cli, args.config)
        data.reset_input_buffer()
        reader = threading.Thread(target=read_frames, args=(data, latest, stop), daemon=True)
        reader.start()
        deadline = time.monotonic() + SNAPSHOT_TIMEOUT_S
        try:
            while args.snapshot is not None or plt.fignum_exists(fig.number):
                try:
                    frame = latest.get(timeout=0.05) if args.snapshot else latest.get_nowait()
                except queue.Empty:
                    if not reader.is_alive():
                        raise RuntimeError("data port reader stopped; see the error above") from None
                    if args.snapshot is not None and time.monotonic() > deadline:
                        raise TimeoutError(f"no frame within {SNAPSHOT_TIMEOUT_S:.0f} s") from None
                    if args.snapshot is None:
                        plt.pause(0.05)
                    continue
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
                plt.pause(0.05)
        finally:
            stop.set()
            cli.write(b"sensorStop\n")
            reader.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
