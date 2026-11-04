# SPDX-License-Identifier: MIT
"""Signal processing of raw DDM and TDM frames [chirp, rx, sample], independent of the firmware.

TDM frames hold one chirp per TX in every loop, in TX order; DDM frames hold every TX on every chirp.
"""

from __future__ import annotations

import numpy as np

DETECTION_DB = 15.0  # peak picking: above the median of the folded map
MIN_RANGE_M = 0.25  # targets start beyond the TX-to-RX leakage in the first range bins
MAX_TARGETS = 10
AZIMUTH_BINS = 128


def doppler_spectrum(frames: np.ndarray) -> np.ndarray:
    """[..., chirp, rx, sample] -> complex [..., Doppler, rx, range] (Hann windows)."""
    num_chirps, num_samples = frames.shape[-3], frames.shape[-1]
    spectrum = np.fft.fft(frames * np.hanning(num_samples), axis=-1)
    return np.fft.fft(spectrum * np.hanning(num_chirps)[:, None, None], axis=-3)


def tdm_spectrum(frames: np.ndarray, num_tx: int) -> np.ndarray:
    """TDM [..., chirp, rx, sample] -> complex [..., Doppler, tx, rx, range]: the Doppler FFT
    runs over the loops, separately for each TX."""
    shape = frames.shape
    by_tx = frames.reshape(*shape[:-3], shape[-3] // num_tx, num_tx, *shape[-2:])  # [..., loop, tx, ...]
    return np.moveaxis(doppler_spectrum(np.moveaxis(by_tx, -3, -4)), -4, -3)


def range_doppler_power(frames: np.ndarray, tdm_tx: int = 0) -> np.ndarray:
    """[frame, chirp, rx, sample] -> power [range, Doppler], summed over antennas, mean over
    frames; tdm_tx > 0 decodes TDM frames with that many TX."""
    if tdm_tx:
        return (np.abs(tdm_spectrum(frames, tdm_tx)) ** 2).sum(axis=(2, 3)).mean(axis=0).T
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
    """Mean log-power over the sub-bands (the folded map that targets are detected on): [range, bin]."""
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


def tdm_virtual_array(spectrum: np.ndarray) -> np.ndarray:
    """One TDM frame's spectrum [Doppler, tx, rx, range] -> virtual array [Doppler, range, tx, rx].

    TX m transmits m chirps after TX0, so a target at signed Doppler bin k has moved by an extra
    2 pi k m / (TX x loops) of phase; that motion phase is removed.
    """
    num_loops, num_tx = spectrum.shape[:2]
    signed_bin = np.fft.fftfreq(num_loops, 1 / num_loops)
    motion = np.exp(-2j * np.pi * np.outer(signed_bin, np.arange(num_tx)) / (num_tx * num_loops))
    return (spectrum * motion[:, :, None, None]).transpose(0, 3, 1, 2)


def signed_doppler_bin(folded_bin: int, tx0: int, width: int, num_chirps: int) -> int:
    """TX0's Doppler bin, -num_chirps/2 .. num_chirps/2-1."""
    doppler_bin = folded_bin + width * tx0
    return doppler_bin - num_chirps if doppler_bin >= num_chirps // 2 else doppler_bin


def decode_frame(frame: np.ndarray, bands: int, num_tx: int,
                 static_loop: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One raw frame [chirp, rx, sample] -> power maps: raw [range, Doppler], decoded
    velocity [range, Doppler] (zero velocity centred) and azimuth [range, angle]. bands 0
    means TDM.

    static_loop, the chirps per loop, removes stationary objects. The decoded maps hold
    only cells DETECTION_DB above the noise; the others would land at arbitrary
    velocities and angles.
    """
    if static_loop is not None:
        frame = remove_static(frame, static_loop)
    if bands:
        spectrum = doppler_spectrum(frame)
        raw = (np.abs(spectrum) ** 2).sum(axis=1).T
        virtual, tx0_bin = ddm_virtual_array(spectrum, bands, num_tx)  # [folded bin, range, ...]
    else:
        spectrum = tdm_spectrum(frame, num_tx)
        raw = (np.abs(spectrum) ** 2).sum(axis=(1, 2)).T
        virtual = tdm_virtual_array(spectrum)  # [Doppler, range, ...]
        tx0_bin = np.broadcast_to(np.arange(raw.shape[1])[:, None], virtual.shape[:2])
    cell_power = (np.abs(virtual) ** 2).sum(axis=(2, 3))
    detected = cell_power > np.median(cell_power) * 10 ** (DETECTION_DB / 10)
    range_bin = np.broadcast_to(np.arange(raw.shape[0]), cell_power.shape)
    velocity = np.zeros_like(raw)
    velocity[range_bin[detected], tx0_bin[detected]] = cell_power[detected]
    # Angle FFT of the detected cells only: the whole cube would cost ~100x more.
    spectra = np.fft.fftshift(np.fft.fft(virtual[detected], AZIMUTH_BINS, axis=1), axes=1)
    azimuth = np.zeros((raw.shape[0], AZIMUTH_BINS))
    np.add.at(azimuth, range_bin[detected], (np.abs(spectra) ** 2).sum(axis=2))
    return raw, np.fft.fftshift(velocity, axes=1), azimuth
