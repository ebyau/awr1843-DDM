# SPDX-License-Identifier: MIT
"""Shared matplotlib styling and the range-Doppler plot with DDM sub-band markers."""

from __future__ import annotations

import numpy as np
from matplotlib.axes import Axes
from matplotlib.image import AxesImage

CMAP = "viridis"  # perceptually uniform, dark (weak) to yellow (strong); as in the xwr demo
INK = "#1f2933"
MUTED = "#6b7785"
DYNAMIC_RANGE_DB = 40.0


def style(ax: Axes, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, color=INK, loc="left")
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.tick_params(colors=MUTED)
    for spine in ax.spines.values():
        spine.set_visible(False)


def band_layout(num_doppler: int, bands: int) -> tuple[int, int]:
    """(Doppler bins per sub-band, shift that puts zero velocity mid-band); no shift
    without sub-bands."""
    width = num_doppler // bands if bands > 0 else num_doppler
    return width, width // 2 if bands > 0 else 0


def centre_bands(values: np.ndarray, bands: int) -> np.ndarray:
    """Rotate the Doppler axis by half a sub-band so zero velocity sits mid-band."""
    return np.roll(values, band_layout(values.shape[1], bands)[1], axis=1)


def draw_axes(ax: Axes, values: np.ndarray, range_step: float, bands: int, title: str) -> AxesImage:
    """Range-Doppler image [range, Doppler] with sub-band boundaries marked, in dB
    (0 at the top of the scale); callers may change the colour limits.

    With sub-bands, the Doppler axis starts half a sub-band below bin 0, so each
    copy of a static target sits in the middle of its sub-band.
    """
    num_range, num_doppler = values.shape
    width, shift = band_layout(num_doppler, bands)
    image = ax.imshow(centre_bands(values, bands), cmap=CMAP, vmin=-DYNAMIC_RANGE_DB, vmax=0,
                      aspect="auto", origin="lower", interpolation="nearest",
                      extent=(-shift - 0.5, num_doppler - shift - 0.5,
                              -range_step / 2, (num_range - 0.5) * range_step))
    style(ax, title, "Doppler bin (unfolded; negative bins wrap from the top)", "Range (m)")
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
