# SPDX-License-Identifier: MIT
"""Live range-Doppler heat map from the mmw demo.

Shows the unfolded Doppler spectrum with the DDM sub-band boundaries marked, so
each target's TX copies and the empty sub-band are visible. The configuration
must enable the range-Doppler heat map (guiMonitor ... 1 ...).

Usage: uv run python host/rd_view.py CONFIG.cfg [--bands N] [--snapshot out.png]
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
from matplotlib.image import AxesImage

from mmw_host import (
    HEATMAP_Q8_TO_DB,
    TLV_RANGE_DOPPLER,
    Frame,
    add_port_args,
    ddm_params,
    frames,
    load_cfg,
    range_axis,
    running_radar,
)
from plotting import INK, centre_bands, draw_axes

SNAPSHOT_TIMEOUT_S = 15.0


def to_db(raw: bytes, num_range_bins: int) -> np.ndarray:
    """Heat map payload -> [range, Doppler] array in dB relative to its peak."""
    heatmap = np.frombuffer(raw, dtype="<u2").reshape(num_range_bins, -1) * HEATMAP_Q8_TO_DB
    return heatmap - heatmap.max()


def read_frames(data: serial.Serial, latest: queue.Queue[Frame], stop: threading.Event) -> None:
    """Read frames continuously, keeping only the newest, so the UART never overflows
    while the plot redraws."""
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            for frame in frames(data):
                with contextlib.suppress(queue.Empty):
                    latest.get_nowait()
                latest.put(frame)
                if stop.is_set():
                    return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--bands", type=int, help="sub-band markers (default: ddmCfg; 0: none)")
    parser.add_argument("--snapshot", type=Path, help="save one frame to this PNG and exit")
    add_port_args(parser)
    args = parser.parse_args()

    cfg = load_cfg(args.config)
    num_range_bins, range_step = range_axis(cfg)
    bands = ddm_params(cfg)[0] if args.bands is None else args.bands
    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    image: AxesImage | None = None
    latest: queue.Queue[Frame] = queue.Queue(maxsize=1)
    stop = threading.Event()

    with running_radar(args.config, args.cli, args.data) as data:
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
                    image = draw_axes(ax, db, range_step, bands, "Range-Doppler map")
                    fig.colorbar(image, ax=ax, label="Level relative to peak (dB)", shrink=0.8)
                else:
                    image.set_data(centre_bands(db, bands))
                ax.set_title(f"Range-Doppler map, frame {frame.number}", color=INK, loc="left")
                if args.snapshot is not None:
                    fig.savefig(args.snapshot, dpi=120)
                    print(f"Saved {args.snapshot}")
                    break
                plt.pause(0.05)
        finally:
            stop.set()
            reader.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
