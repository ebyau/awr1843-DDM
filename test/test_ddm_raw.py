# SPDX-License-Identifier: MIT
"""Unit tests for raw DDM capture decoding; no hardware needed."""

from pathlib import Path

import numpy as np
import pytest

from ddm_raw import (
    chirp_axes,
    ddm_virtual_array,
    doppler_spectrum,
    find_targets,
    fold,
    min_range_m,
    range_doppler_power,
    remove_static,
    signed_doppler_bin,
    tx0_band,
)
from mmw_host import parse_cfg
from raw_capture import iiqq_to_complex, raw_frame_shape

RAW_CFG = Path(__file__).parents[1] / "host" / "profiles" / "ddm_aop_raw.cfg"


def to_iiqq(iq: np.ndarray) -> bytes:
    """Inverse of iiqq_to_complex: Q0 Q1 I0 I1 Q2 Q3 I2 I3 ... per RX."""
    iiqq = np.empty((*iq.shape[:-1], 2 * iq.shape[-1]), dtype="<i2")
    iiqq[..., 0::4], iiqq[..., 1::4] = iq.imag[..., 0::2], iq.imag[..., 1::2]
    iiqq[..., 2::4], iiqq[..., 3::4] = iq.real[..., 0::2], iq.real[..., 1::2]
    return iiqq.tobytes()


def test_raw_frame_shape_from_profile() -> None:
    assert raw_frame_shape(parse_cfg(RAW_CFG.read_text())) == (128, 4, 256)


@pytest.mark.parametrize(("line", "replacement", "message"), [
    ("lvdsStreamCfg -1 0 1 0", "lvdsStreamCfg -1 0 0 0", "LVDS"),  # processed output
    ("lvdsStreamCfg -1 0 1 0", "lvdsStreamCfg -1 1 1 0", "LVDS"),  # header in the stream
    ("adcCfg 2 1", "adcCfg 2 0", "complex"),                       # real ADC samples
])
def test_raw_frame_shape_rejects_unsupported_streams(line: str, replacement: str, message: str) -> None:
    cfg = parse_cfg(RAW_CFG.read_text().replace(line, replacement))
    with pytest.raises(ValueError, match=message):
        raw_frame_shape(cfg)


def test_iiqq_byte_order() -> None:
    """Q0 Q1 I0 I1 from the capture card is I0+jQ0, I1+jQ1."""
    data = np.array([1, 2, 3, 4], dtype="<i2").tobytes()
    assert np.array_equal(iiqq_to_complex(data, (1, 1, 2)), np.array([[[3 + 1j, 4 + 2j]]]))


def test_iiqq_round_trip() -> None:
    rng = np.random.default_rng(0)
    shape = (4, 2, 8)
    iq = (rng.integers(-2000, 2000, shape) + 1j * rng.integers(-2000, 2000, shape)).astype(np.complex64)
    assert np.array_equal(iiqq_to_complex(to_iiqq(iq), shape), iq)


def test_min_range_from_cfar_range_window() -> None:
    assert min_range_m(parse_cfg(RAW_CFG.read_text())) == 0.25
    assert min_range_m(parse_cfg("profileCfg 0\n")) == 0.0


def test_chirp_axes_match_firmware_profile() -> None:
    range_step, velocity_step = chirp_axes(parse_cfg(RAW_CFG.read_text()), 128)
    assert range_step == pytest.approx(0.0422, rel=1e-2)
    assert velocity_step == pytest.approx(0.322, rel=1e-2)


@pytest.mark.parametrize("doppler_bin", [0, 5, 31, 40, 100, 127])
def test_simulated_ddm_target_is_resolved(doppler_bin: int) -> None:
    """Three phase-coded TX copies of one target: TX k lands k sub-bands above TX0."""
    chirps, rx, samples, bands, num_tx, range_bin = 128, 4, 256, 4, 3, 60
    n = np.arange(chirps)[:, None, None]
    s = np.arange(samples)
    tone = sum(np.exp(2j * np.pi * (doppler_bin * n / chirps + k * n / bands + range_bin * s / samples))
               for k in range(num_tx))
    rng = np.random.default_rng(1)
    noise = rng.normal(size=(chirps, rx, samples)) + 1j * rng.normal(size=(chirps, rx, samples))
    power = range_doppler_power((tone + 0.1 * noise)[None])

    (target_range, folded_bin), *_ = find_targets(fold(power, bands))
    width = chirps // bands
    tx0 = tx0_band(power[target_range, folded_bin::width], num_tx)
    assert target_range == range_bin
    assert signed_doppler_bin(folded_bin, tx0, width, chirps) == (doppler_bin + 64) % chirps - 64


def ddm_frame(doppler_bin: int, range_bin: int, antenna_phase: np.ndarray) -> np.ndarray:
    """One noiseless DDM frame [chirp, rx, sample]: 3 phase-coded TX, 4 sub-bands."""
    n = np.arange(128)[:, None, None]
    s = np.arange(256)
    return sum(np.exp(2j * np.pi * (doppler_bin * n / 128 + k * n / 4 + range_bin * s / 256)
                      + 1j * antenna_phase[k][None, :, None]) for k in range(3))


def test_remove_static_removes_every_tx_copy_of_static_targets() -> None:
    phase = np.zeros((3, 4))
    static = ddm_frame(0, 20, phase)
    moving = ddm_frame(-10, 40, phase)
    power = (np.abs(doppler_spectrum(remove_static(static + moving, 4))) ** 2).sum(axis=1)
    assert power[[0, 32, 64, 96], 20].max() < 1e-6 * power.max()
    assert power[(-10 + 128) % 128, 40] == pytest.approx(power.max(), rel=0.01)  # moving target kept


def test_ddm_virtual_array_separates_tx_copies() -> None:
    phase = np.random.default_rng(2).uniform(-np.pi, np.pi, (3, 4))
    virtual, tx0_bin = ddm_virtual_array(doppler_spectrum(ddm_frame(-10, 20, phase)), 4, 3)
    folded = (-10) % 32
    assert tx0_bin[folded, 20] == (-10) % 128
    measured = np.angle(virtual[folded, 20] / virtual[folded, 20, 0, 0])
    expected = phase - phase[0, 0]
    assert np.allclose(np.angle(np.exp(1j * (measured - expected))), 0, atol=1e-3)
