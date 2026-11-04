# SPDX-License-Identifier: MIT
"""Hardware limits of the AWR1843AOP and the raw-data DDM firmware, checked on a parsed configuration."""

from __future__ import annotations

import math

from .cfg import (
    Config,
    cfg_args,
    chirp_period_us,
    chirps_per_frame,
    chirps_per_loop,
    ddm_params,
    profile,
    sampling_end_us,
)

MAX_BANDS = 16
PHASE_SHIFTER_STEPS = 64  # the sub-band count must divide this
MAX_CHIRPS_PER_LOOP = 32  # chirp table of the firmware's RF parser
MAX_LOOPS = 255
FRAME_BLANK_MS = 0.3  # idle time the radar subsystem needs between frames
ADC_BUFFER_BYTES = 16 * 1024  # one ping-pong half of the 32 KB ADC buffer holds one chirp
RF_BAND_GHZ = (76.0, 81.0)
# profileCfg maxima of the RF front end (rlProfileCfg_t in TI's rl_sensor.h, 10 ns steps)
PROFILE_MAX_US = {"idle_us": 524287 * 0.01, "ramp_end_us": 500000 * 0.01}


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
        if chirps_per_loop(cfg) != bands:
            problems.append(f"DDM needs {bands} chirps per loop (frameCfg), one per sub-band; "
                            f"got {chirps_per_loop(cfg)}")
        first, last = (int(f) for f in cfg_args(cfg, "frameCfg")[:2])
        masks = {args[7] for args in cfg["chirpCfg"]
                 if int(args[0]) <= last and int(args[1]) >= first}  # chirpCfg start, end index
        if len(masks) > 1:
            problems.append("DDM needs the same TX mask on every chirp of the loop; "
                            f"got {', '.join(sorted(masks))}")

    if chirps_per_loop(cfg) > MAX_CHIRPS_PER_LOOP:
        problems.append(f"{chirps_per_loop(cfg)} chirps per loop; at most {MAX_CHIRPS_PER_LOOP}")

    loops = int(cfg_args(cfg, "frameCfg")[2])
    if not 1 <= loops <= MAX_LOOPS:
        problems.append(f"{loops} loops per frame; 1 to {MAX_LOOPS}")

    p = profile(cfg)
    num_rx = int(cfg_args(cfg, "channelCfg")[0]).bit_count()
    channel_bytes = math.ceil(p["samples"] * 4 / 16) * 16  # complex 16-bit, each RX padded to 16 B
    if channel_bytes * num_rx > ADC_BUFFER_BYTES:
        problems.append(f"{p['samples']:g} complex samples x {num_rx} RX ({channel_bytes} B per RX) exceed "
                        f"the {ADC_BUFFER_BYTES // 1024} KB ADC buffer per chirp")
    for name, max_us in PROFILE_MAX_US.items():
        if p[name] > max_us:
            problems.append(f"profileCfg {name} = {p[name]:g} us; at most {max_us:g} us")
    if sampling_end_us(cfg) > p["ramp_end_us"]:
        problems.append(f"ADC sampling ends at {sampling_end_us(cfg):.2f} us, after the ramp end "
                        f"({p['ramp_end_us']:g} us)")

    period_ms = float(cfg_args(cfg, "frameCfg")[4])
    burst_ms = chirps_per_frame(cfg) * chirp_period_us(cfg) / 1e3
    if burst_ms + FRAME_BLANK_MS > period_ms:
        problems.append(f"chirps take {burst_ms:.2f} ms; with the {FRAME_BLANK_MS:g} ms blank time between "
                        f"frames that exceeds the {period_ms:g} ms frame period")

    rf_end_ghz = p["start_ghz"] + p["slope_mhz_per_us"] * p["ramp_end_us"] / 1e3  # slope may be negative
    if min(p["start_ghz"], rf_end_ghz) < RF_BAND_GHZ[0] or max(p["start_ghz"], rf_end_ghz) > RF_BAND_GHZ[1]:
        problems.append(f"chirp sweeps {p['start_ghz']:g}-{rf_end_ghz:g} GHz, outside "
                        f"{RF_BAND_GHZ[0]:g}-{RF_BAND_GHZ[1]:g} GHz")
    return problems
