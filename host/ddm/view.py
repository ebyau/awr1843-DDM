# SPDX-License-Identifier: MIT
"""Live matplotlib view of raw frames from the capture card."""

from __future__ import annotations

import contextlib
import logging
import queue
import threading
from collections.abc import Iterator

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.artist import Artist
from matplotlib.image import AxesImage

from .cfg import Config, chirp_axes, chirps_per_loop, doppler_bins, mimo_params, raw_frame_shape
from .dca import capture, open_capture_card
from .dsp import AZIMUTH_BINS, decode_frame
from .plotting import CMAP, centre_bands, draw_axes, style

log = logging.getLogger(__name__)

TOP_VIEW_PIXELS = 256  # along y; x has twice as many
GAMMA = 0.5
PCLIP = 0.1
POLL_MS = 10


def top_view_lookup(num_range: int, range_step: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(range bin, azimuth bin, inside field of view) for each pixel of the top view.

    Azimuth bin k of the shifted angle FFT is sin(angle) = 2k/AZIMUTH_BINS - 1 for a
    half-wavelength array.
    """
    max_range = num_range * range_step
    x, y = np.meshgrid(np.linspace(-max_range, max_range, 2 * TOP_VIEW_PIXELS),
                       np.linspace(0, max_range, TOP_VIEW_PIXELS))
    radius = np.hypot(x, y)
    sin_angle = np.divide(x, radius, out=np.zeros_like(x), where=radius > 0)
    range_bin = np.round(radius / range_step).astype(int)
    azimuth_bin = np.round((sin_angle + 1) * AZIMUTH_BINS / 2).astype(int)
    inside = range_bin < num_range
    return np.minimum(range_bin, num_range - 1), np.minimum(azimuth_bin, AZIMUTH_BINS - 1), inside


def show(image: AxesImage, power: np.ndarray, pclip: float = PCLIP, gamma: float = GAMMA) -> None:
    """Displays amplitude ** gamma with the colour scale clipped to the pclip percentiles.

    Sparse maps (only detected cells) use pclip 0, so a few cells are not clipped away.
    """
    values = np.sqrt(power) ** gamma
    low, high = np.nanpercentile(values, [pclip, 100 - pclip])
    image.set_data(values)
    image.set_clim(low, max(high, low + 1e-9))


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


def live_view(cfg_text: str, cfg: Config, cli_port: str, hide_static: bool) -> None:
    """Live raw-data view from the capture card (DDM or TDM): raw range-Doppler, decoded
    range-velocity and top view. Brightness follows the xwr demo: amplitude raised to GAMMA (linear in the
    top view), the colour scale clipped to the PCLIP percentiles."""
    bands, num_tx = mimo_params(cfg)
    static_loop = chirps_per_loop(cfg) if hide_static else None
    num_chirps, _, num_range = raw_frame_shape(cfg)
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    max_range = num_range * range_step
    num_doppler = doppler_bins(cfg)
    max_velocity = num_doppler / 2 * velocity_step
    range_bin, azimuth_bin, inside = top_view_lookup(num_range, range_step)

    fig, (ax_raw, ax_vel, ax_top) = plt.subplots(1, 3, figsize=(15, 5.5), layout="constrained")
    empty = np.zeros((num_range, num_doppler))
    raw_image = draw_axes(ax_raw, empty, range_step, bands, "Raw: one copy per TX" if bands else "Raw (TDM)")
    vel_image = ax_vel.imshow(empty, cmap=CMAP, aspect="auto", origin="lower", interpolation="nearest",
                              extent=(-max_velocity - velocity_step / 2, max_velocity - velocity_step / 2,
                                      -range_step / 2, max_range - range_step / 2))
    style(ax_vel, "DDM decoded" if bands else "TDM detected", "Radial velocity (m/s)", "Range (m)")
    top_image = ax_top.imshow(np.zeros(inside.shape), cmap=CMAP, aspect="equal", origin="lower",
                              extent=(-max_range, max_range, 0, max_range))
    style(ax_top, f"Top view ({num_tx}-TX virtual array)", "x (m)", "y (m)")

    # Blitting redraws only these artists; the band lines go last to stay on top.
    artists: list[Artist] = [raw_image, vel_image, top_image, *ax_raw.lines]
    latest: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
    stop = threading.Event()
    stream = capture(cfg_text, cli_port, open_capture_card())
    reader = threading.Thread(target=read_raw_frames, args=(stream, latest, stop), daemon=True)

    def update(_: int) -> list[Artist]:
        try:
            frame = latest.get_nowait()
        except queue.Empty:
            if not reader.is_alive():
                plt.close(fig)
            return []  # nothing new to redraw
        raw, velocity, azimuth = decode_frame(frame, bands, num_tx, static_loop)
        show(raw_image, centre_bands(raw, bands))
        show(vel_image, velocity, pclip=0)
        # Linear amplitude, as in the xwr demo: the wide beam's sidelobes stay dark.
        show(top_image, np.where(inside, azimuth[range_bin, azimuth_bin], np.nan), pclip=0, gamma=1)
        return artists

    reader.start()
    try:
        # Poll often: the timer waits its interval after each update, not from its start.
        _animation = FuncAnimation(fig, update, interval=POLL_MS, blit=True, cache_frame_data=False)
        plt.show()
        if not reader.is_alive():
            raise RuntimeError("capture stopped; see the error above")
    finally:
        stop.set()
        reader.join(timeout=5)
        if reader.is_alive():
            log.warning("capture did not stop; send sensorStop to the radar before the next run")
