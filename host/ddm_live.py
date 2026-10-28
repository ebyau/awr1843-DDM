# SPDX-License-Identifier: MIT
"""Live view of raw DDM frames from a DCA1000EVM capture card.

Three panels, updated as frames arrive: the raw range-Doppler map with its TX copies
in the sub-bands, the range-velocity map after DDM separates the TX copies (full
unambiguous velocity), and a top-down view from the virtual array. On the AWR1843AOP
the three TX antennas form the horizontal axis of the virtual array, so the top view
exists only because DDM separates them. Close the window to stop.

Brightness follows the xwr demo: amplitude raised to GAMMA (linear amplitude in the
top view), with the colour scale clipped to the PCLIP percentiles, so noise and
sidelobes stay dark.

Usage: uv run python host/ddm_live.py CONFIG.cfg [--bands 4] [--tx 3] [--remove-static]
"""

from __future__ import annotations

import argparse
import contextlib
import queue
import sys
import threading
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.image import AxesImage
from xwr import DCAConfig

from ddm_raw import DETECTION_DB, chirp_axes, ddm_virtual_array, doppler_spectrum, remove_static
from raw_capture import capture, parse_cfg, raw_frame_shape
from rd_view import CMAP, INK, MUTED, centre_bands, draw_axes

AZIMUTH_BINS = 128
TOP_VIEW_PIXELS = 256  # along y; x has twice as many
GAMMA = 0.5
PCLIP = 0.1


def decode(frame: np.ndarray, bands: int, num_tx: int, static: bool) -> tuple[np.ndarray, ...]:
    """One raw frame [chirp, rx, sample] -> power maps: raw [range, Doppler], decoded
    velocity [range, Doppler] and azimuth [range, angle].

    The decoded maps hold only cells DETECTION_DB above the noise; the others would
    land at arbitrary velocities and angles.
    """
    spectrum = doppler_spectrum(frame if static else remove_static(frame, bands))
    raw = (np.abs(spectrum) ** 2).sum(axis=1).T
    virtual, tx0_bin = ddm_virtual_array(spectrum, bands, num_tx)  # [folded bin, range, ...]
    cell_power = (np.abs(virtual) ** 2).sum(axis=(2, 3))
    detected = cell_power > np.median(cell_power) * 10 ** (DETECTION_DB / 10)
    range_bin = np.broadcast_to(np.arange(raw.shape[0]), cell_power.shape)
    velocity = np.zeros_like(raw)
    velocity[range_bin[detected], tx0_bin[detected]] = cell_power[detected]
    azimuth = np.abs(np.fft.fftshift(np.fft.fft(virtual, AZIMUTH_BINS, axis=2), axes=2)) ** 2
    azimuth = (azimuth * detected[:, :, None, None]).sum(axis=(0, 3))
    return raw, np.fft.fftshift(velocity, axes=1), azimuth


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


def style(ax: plt.Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, color=INK, loc="left")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_visible(False)


def read_frames(stream, latest: queue.Queue[np.ndarray], stop: threading.Event) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("config", type=Path)
    parser.add_argument("--bands", type=int, default=4)
    parser.add_argument("--tx", type=int, default=3)
    parser.add_argument("--remove-static", action="store_true", help="hide stationary objects")
    parser.add_argument("--cli", default="/dev/ttyUSB0")
    args = parser.parse_args()

    cfg = parse_cfg(args.config.read_text())
    num_chirps, _, num_range = raw_frame_shape(cfg)
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    max_range = num_range * range_step
    max_velocity = num_chirps / 2 * velocity_step
    range_bin, azimuth_bin, inside = top_view_lookup(num_range, range_step)

    fig, (ax_raw, ax_vel, ax_top) = plt.subplots(1, 3, figsize=(15, 5.5), layout="constrained")
    empty = np.zeros((num_range, num_chirps))
    raw_image = draw_axes(ax_raw, empty, range_step, args.bands)
    ax_raw.set_title("Raw: one copy per TX", color=INK, loc="left")
    vel_image = ax_vel.imshow(empty, cmap=CMAP, aspect="auto", origin="lower", interpolation="nearest",
                              extent=(-max_velocity, max_velocity, 0, max_range))
    style(ax_vel, "DDM decoded", "Radial velocity (m/s)", "Range (m)")
    top_image = ax_top.imshow(np.zeros(inside.shape), cmap=CMAP, aspect="equal", origin="lower",
                              extent=(-max_range, max_range, 0, max_range))
    style(ax_top, "Top view (3-TX virtual array)", "x (m)", "y (m)")

    latest: queue.Queue[np.ndarray] = queue.Queue(maxsize=1)
    stop = threading.Event()
    stream = capture(args.config, args.cli, DCAConfig(timeout=3.0).create())
    reader = threading.Thread(target=read_frames, args=(stream, latest, stop), daemon=True)
    reader.start()
    try:
        while plt.fignum_exists(fig.number):
            try:
                frame = latest.get_nowait()
            except queue.Empty:
                if not reader.is_alive():
                    raise RuntimeError("capture stopped; see the error above") from None
                plt.pause(0.02)
                continue
            raw, velocity, azimuth = decode(frame, args.bands, args.tx, not args.remove_static)
            show(raw_image, centre_bands(raw, args.bands))
            show(vel_image, velocity, pclip=0)
            # Linear amplitude, as in the xwr demo: the wide 3-element beam's sidelobes stay dark.
            show(top_image, np.where(inside, azimuth[range_bin, azimuth_bin], np.nan), pclip=0, gamma=1)
            plt.pause(0.02)
    finally:
        stop.set()
        reader.join(timeout=5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
