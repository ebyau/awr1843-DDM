# SPDX-License-Identifier: MIT
"""Raw-signal plots: live from the capture card, or replayed from a capture file.

The range-Doppler spectrum of RX 0 with no processing besides the FFTs: no window, as
20 log10 |FFT| on a fixed scale.
"""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .cfg import Config, cfg_args, chirp_axes, ddm_params, raw_frame_shape
from .dca import capture, open_capture_card
from .rawdata import iq_to_complex, spectrum

log = logging.getLogger(__name__)

POLL_MS = 10
CMAP = "viridis"  # perceptually uniform, dark (weak) to yellow (strong)
INK, MUTED = "#1f2933", "#6b7785"
RAW_RANGE_DB = 80.0  # spectrum colour scale: this far below the first frame's peak

Draw = Callable[[np.ndarray], None]


def style(ax: Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, color=INK, loc="left")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_visible(False)


def raw_figure(cfg: Config) -> tuple[Figure, Draw]:
    """The figure and a function that draws one complex frame [chirp, rx, sample] on it."""
    bands, _ = ddm_params(cfg)
    num_chirps, _, num_range = raw_frame_shape(cfg)
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    half = num_chirps // 2

    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    image = ax.imshow(np.zeros((num_range, num_chirps)), cmap=CMAP, aspect="auto", origin="lower",
                      interpolation="nearest",
                      extent=(-half - 0.5, num_chirps - half - 0.5,
                              -range_step / 2, (num_range - 0.5) * range_step))
    style(ax, f"Spectrum, RX 0, no window ({velocity_step:.3g} m/s per bin)",
          "Doppler bin (every chirp; DDM: TX k shifted k sub-bands)", "Range (m)")
    for band in range(1, bands):  # sub-band edges, as markers only
        ax.axvline(band * num_chirps / bands - half - 0.5, color="white", alpha=0.5, linewidth=1,
                   linestyle=(0, (4, 3)))
    fig.colorbar(image, ax=ax, label="dB re 1 ADC count", shrink=0.8)
    scaled = False

    def draw(frame: np.ndarray) -> None:
        nonlocal scaled
        db = 20 * np.log10(np.abs(np.fft.fftshift(spectrum(frame[:, :1])[:, 0], axes=0)).T + 1e-6)
        image.set_data(db)
        if not scaled:  # the colour scale is fixed by the first frame
            peak = np.ceil(db.max() / 10) * 10
            image.set_clim(peak - RAW_RANGE_DB, peak)
            scaled = True
    return fig, draw


def read_raw_frames(stream: Iterator[np.ndarray], latest: queue.Queue[np.ndarray],
                    stop: threading.Event) -> None:
    """Keep only the newest frame so slow plotting never backs up the capture."""
    try:
        for frame in stream:
            if stop.is_set():
                break
            with contextlib.suppress(queue.Empty):
                latest.get_nowait()
            latest.put(frame)
    finally:
        stream.close()


def live_view(cfg_text: str, cfg: Config, cli_port: str) -> None:
    """Streams frames from the capture card and plots the newest until the window closes."""
    fig, draw = raw_figure(cfg)
    latest: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
    stop = threading.Event()
    stream = capture(cfg_text, cli_port, open_capture_card())
    reader = threading.Thread(target=read_raw_frames, args=(stream, latest, stop), daemon=True)

    def update(_: int) -> list:
        try:
            draw(iq_to_complex(latest.get_nowait()))
        except queue.Empty:
            if not reader.is_alive():
                plt.close(fig)
        return []

    reader.start()
    try:
        # Poll often: the timer waits its interval after each update, not from its start.
        _animation = FuncAnimation(fig, update, interval=POLL_MS, cache_frame_data=False)
        plt.show()
        if not reader.is_alive():
            raise RuntimeError("capture stopped; see the error above")
    finally:
        stop.set()
        reader.join(timeout=5)
        if reader.is_alive():
            log.warning("capture did not stop; send sensorStop to the radar before the next run")


def replay(frames: np.ndarray, cfg: Config) -> None:
    """Plays complex frames [frame, chirp, rx, sample] in a loop at the frame period."""
    fig, draw = raw_figure(cfg)
    period_ms = float(cfg_args(cfg, "frameCfg")[4])
    _animation = FuncAnimation(fig, lambda i: draw(frames[i % len(frames)]), interval=period_ms,
                               cache_frame_data=False)
    plt.show()


def snapshot(frame: np.ndarray, cfg: Config, path: Path) -> None:
    """Saves the plot of one complex frame [chirp, rx, sample] as an image."""
    fig, draw = raw_figure(cfg)
    draw(frame)
    fig.savefig(path, dpi=120)
