# SPDX-License-Identifier: MIT
"""Raw ADC capture through a DCA1000EVM capture card, driven by xwr (github.com/RadarML/xwr).

The configuration must stream ADC samples over LVDS (lvdsStreamCfg -1 0 1 0) with
complex 16-bit samples. Byte order and storage: rawdata.py.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import NamedTuple

import numpy as np
from xwr import DCAConfig
from xwr.capture import DCA1000EVM

from .cfg import parse_cfg, raw_frame_shape
from .radar import open_cli, send_config, sensor_stop
from .rawdata import iiqq_to_iq

log = logging.getLogger(__name__)

CAPTURE_TIMEOUT_S = 3.0  # the stream ends when no data arrives for this long


class Frame(NamedTuple):
    iq: np.ndarray    # int16 [chirp, rx, sample, 2] (I, Q)
    timestamp: float  # PC clock (Unix s) when the host read the frame's first data
    complete: bool    # False: the capture card lost data; the contents are unreliable


def open_capture_card() -> DCA1000EVM:
    """Capture card at xwr's default addresses (PC 192.168.33.30, card 192.168.33.180)."""
    return DCAConfig(timeout=CAPTURE_TIMEOUT_S).create()


def capture(cfg_text: str, cli_port: str, dca: DCA1000EVM) -> Iterator[Frame]:
    """Configure and start the radar, then yield every raw frame until closed.

    Frames with lost data are yielded too, marked incomplete, so the frames stay one
    frame period apart. Needs xwr's C receiver: its pure-Python fallback can mark a frame
    with lost data as complete.

    The capture card starts after the radar stops and before it restarts, so that
    its byte count, which sets the frame boundaries, starts at the first chirp.
    """
    try:
        from xwr.capture import _fast  # noqa: F401
    except ImportError as err:
        raise RuntimeError("xwr's C receiver (xwr.capture._fast) is missing; without it lost data "
                           "can go unmarked. Reinstall xwr: uv sync --reinstall-package xwr") from err
    shape = raw_frame_shape(parse_cfg(cfg_text))
    with open_cli(cli_port) as cli:
        sensor_stop(cli, wait=True)
        dca.stop()
        dca.flush()
        dca.start()
        try:
            send_config(cli, cfg_text)
            for frame in dca.stream([*shape[:-1], 2 * shape[-1]]):
                if not frame.complete:
                    log.warning("incomplete frame: the capture card lost data (zero-filled)")
                yield Frame(iiqq_to_iq(frame.data, shape), frame.timestamp, frame.complete)
        finally:
            sensor_stop(cli)
            dca.stop()
