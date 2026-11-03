# SPDX-License-Identifier: MIT
"""Hardware limits of the AWR1843AOP and the DDM firmware, checked on a parsed configuration."""

from __future__ import annotations

from .cfg import (
    Config,
    cfg_args,
    chirp_period_us,
    chirps_per_frame,
    chirps_per_loop,
    ddm_params,
    doppler_bins,
    profile,
    range_axis,
    sampling_end_us,
)
from .radar import DATA_BAUD

MAX_BANDS = 16
PHASE_SHIFTER_STEPS = 64  # the sub-band count must divide this
MAX_CHIRPS_PER_LOOP = 32
CFAR_MATRIX_MAX_BYTES = 32 * 1024  # detection matrix limit of the hardware accelerator
UART_BITS_PER_BYTE = 10  # start + 8 data + stop
RF_BAND_GHZ = (76.0, 81.0)


def check(cfg: Config) -> list[str]:
    """Descriptions of every limit the configuration violates; empty if none."""
    problems = []
    bands, num_tx = ddm_params(cfg)
    if bands:
        if PHASE_SHIFTER_STEPS % bands or not num_tx < bands <= MAX_BANDS:
            problems.append(f"ddmCfg {bands}: the sub-band count must divide {PHASE_SHIFTER_STEPS}, "
                            f"exceed the {num_tx} TX and be at most {MAX_BANDS}")
        if num_tx < 2 or int(cfg_args(cfg, "chirpCfg")[7]) != (1 << num_tx) - 1:
            problems.append("DDM needs at least 2 TX, contiguous from TX0 (chirpCfg TX mask 3, 7, ...)")

    if chirps_per_loop(cfg) > MAX_CHIRPS_PER_LOOP:
        problems.append(f"{chirps_per_loop(cfg)} chirps per loop; at most {MAX_CHIRPS_PER_LOOP}")

    num_range = range_axis(cfg)[0]
    folded = doppler_bins(cfg) // bands if bands else doppler_bins(cfg)
    if num_range * folded * 2 > CFAR_MATRIX_MAX_BYTES:
        problems.append(f"CFAR detection matrix {num_range} x {folded} x 2 B exceeds "
                        f"{CFAR_MATRIX_MAX_BYTES // 1024} KB")

    p = profile(cfg)
    if sampling_end_us(cfg) > p["ramp_end_us"]:
        problems.append(f"ADC sampling ends at {sampling_end_us(cfg):.2f} us, after the ramp end "
                        f"({p['ramp_end_us']:g} us)")

    period_ms = float(cfg_args(cfg, "frameCfg")[4])
    burst_ms = chirps_per_frame(cfg) * chirp_period_us(cfg) / 1e3
    if burst_ms >= period_ms:
        problems.append(f"chirps take {burst_ms:.2f} ms, not less than the {period_ms:g} ms frame period")

    gui = cfg.get("guiMonitor", [[]])[0]
    if len(gui) > 5 and gui[5] != "0":
        uart_ms = num_range * doppler_bins(cfg) * 2 * UART_BITS_PER_BYTE / DATA_BAUD * 1e3
        if uart_ms >= period_ms:
            problems.append(f"the range-Doppler heat map takes {uart_ms:.0f} ms on the UART, not less "
                            f"than the {period_ms:g} ms frame period")

    rf_end_ghz = p["start_ghz"] + p["slope_mhz_per_us"] * p["ramp_end_us"] / 1e3
    if p["start_ghz"] < RF_BAND_GHZ[0] or rf_end_ghz > RF_BAND_GHZ[1]:
        problems.append(f"chirp sweeps {p['start_ghz']:g}-{rf_end_ghz:g} GHz, outside "
                        f"{RF_BAND_GHZ[0]:g}-{RF_BAND_GHZ[1]:g} GHz")
    return problems
