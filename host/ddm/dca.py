# SPDX-License-Identifier: MIT
"""Raw ADC capture through a DCA1000EVM capture card, driven by xwr (github.com/RadarML/xwr).

The configuration must stream ADC samples over LVDS (lvdsStreamCfg -1 0 1 0) with
complex 16-bit samples.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import numpy as np
from xwr import DCAConfig
from xwr.capture import DCA1000EVM

from .cfg import parse_cfg, raw_frame_shape
from .radar import open_cli, send_config, sensor_stop

log = logging.getLogger(__name__)

CAPTURE_TIMEOUT_S = 3.0  # the stream ends when no data arrives for this long


def open_capture_card() -> DCA1000EVM:
    """Capture card at xwr's default addresses (PC 192.168.33.30, card 192.168.33.180)."""
    return DCAConfig(timeout=CAPTURE_TIMEOUT_S).create()


def iiqq_to_complex(data: bytes | bytearray, shape: tuple[int, int, int]) -> np.ndarray:
    """Capture-card byte stream -> complex64 [chirp, rx, sample].

    Two LVDS lanes carry alternate samples, Q before I, and the card interleaves
    them as Q0 Q1 I0 I1 Q2 Q3 I2 I3 ...
    """
    iiqq = np.frombuffer(data, dtype="<i2").reshape(*shape[:-1], 2 * shape[-1]).astype(np.float32)
    iq = np.empty(shape, dtype=np.complex64)
    iq[..., 0::2] = iiqq[..., 2::4] + 1j * iiqq[..., 0::4]
    iq[..., 1::2] = iiqq[..., 3::4] + 1j * iiqq[..., 1::4]
    return iq


def capture(cfg_text: str, cli_port: str, dca: DCA1000EVM) -> Iterator[np.ndarray]:
    """Configure and start the radar, then yield complete raw frames [chirp, rx, sample]
    until closed.

    The capture card starts after the radar stops and before it restarts, so that
    its byte count, which sets the frame boundaries, starts at the first chirp.
    """
    shape = raw_frame_shape(parse_cfg(cfg_text))
    with open_cli(cli_port) as cli:
        sensor_stop(cli, wait=True)
        dca.stop()
        dca.flush()
        dca.start()
        try:
            send_config(cli, cfg_text)
            for frame in dca.stream([*shape[:-1], 2 * shape[-1]]):
                if frame.complete:
                    yield iiqq_to_complex(frame.data, shape)
                else:
                    log.warning("skipped incomplete frame")
        finally:
            sensor_stop(cli)
            dca.stop()
