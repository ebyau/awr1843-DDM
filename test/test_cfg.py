# SPDX-License-Identifier: MIT
"""Unit tests for configuration parsing. Run: uv run pytest"""

from __future__ import annotations

import pytest

from ddm.cfg import ddm_params, parse_cfg, range_axis


def test_range_axis_has_one_bin_per_sample() -> None:
    cfg = parse_cfg("% comment\nprofileCfg 0 77 7 3 39 0 0 100 1 200 7200 0 0 30\n")
    num_bins, step = range_axis(cfg)

    assert num_bins == 200
    assert step == pytest.approx(0.05398, rel=1e-3)  # c * fs / (2 * slope * 200)


def test_parse_cfg_keeps_every_occurrence() -> None:
    cfg = parse_cfg("chirpCfg 0 0 0 0 0 0 0 7\n% comment\nchirpCfg 1 1 0 0 0 0 0 7\n")
    assert cfg["chirpCfg"] == [["0"] * 7 + ["7"], ["1", "1"] + ["0"] * 5 + ["7"]]


@pytest.mark.parametrize(("text", "expected"), [
    ("chirpCfg 0 0 0 0 0 0 0 7\nddmCfg 4\n", (4, 3)),   # DDM, 3 TX per chirp
    ("chirpCfg 0 0 0 0 0 0 0 1\nchirpCfg 1 1 0 0 0 0 0 2\n", (0, 1)),  # TDM
])
def test_ddm_params(text: str, expected: tuple[int, int]) -> None:
    assert ddm_params(parse_cfg(text)) == expected
