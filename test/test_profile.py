# SPDX-License-Identifier: MIT
"""Unit tests for TOML profiles: rendering per command and the golden .cfg fixtures."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ddm.cfg import parse_cfg
from ddm.profile import Profile, derived, load, read, render

ROOT = Path(__file__).parents[1]
DATA = ROOT / "test" / "data"
FIXTURE = DATA / "aop.toml"  # TI's profile_3d_aop.cfg chirp
PROFILE = ROOT / "profiles" / "template.toml"
TI_PROFILE = ROOT / "sdk/packages/ti/demo/xwr18xx/mmw/profiles/profile_3d_aop.cfg"


def commands(text: str) -> list[list[str]]:
    """Command lines in order, comments and blank lines skipped."""
    return [line.split() for line in text.splitlines() if line.split() and not line.startswith("%")]


def aop(**overrides: dict) -> Profile:
    profile = read(FIXTURE)
    for table, values in overrides.items():
        profile[table].update(values)
    return profile


@pytest.mark.parametrize(("use", "fixture", "overrides"), [
    ("capture", "raw", {}),
    ("points", "points", {}),
    ("heatmap", "heatmap", {}),  # frame period raised from 100 to 1000 ms
    ("capture", "raw_fine", {"chirp": {"idle_us": 435}, "frame": {"loops": 16, "period_ms": 50}}),
    ("points", "tdm", {"mimo": {"tdm": True}, "cfar": {"doppler_mps": [-7.06, 12]}}),
])
def test_fixture_renders_golden_cfg(use: str, fixture: str, overrides: dict) -> None:
    text = render(aop(**overrides), use)
    assert commands(text) == commands((DATA / f"{fixture}.cfg").read_text())


def test_every_fixture_is_tested() -> None:
    assert {p.stem for p in DATA.glob("*.cfg")} == {"raw", "points", "heatmap", "raw_fine", "tdm"}


def test_heatmap_raises_short_frame_period(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        cfg = parse_cfg(render(aop(), "heatmap"))
    assert cfg["frameCfg"][0][4] == "1000"
    assert "raised" in caplog.text
    assert parse_cfg(render(aop(frame={"period_ms": 2000}), "heatmap"))["frameCfg"][0][4] == "2000"


def test_load_checks_profile_and_sends_ti_cfg_unchanged(caplog: pytest.LogCaptureFixture) -> None:
    assert load(PROFILE, "points")[0].splitlines()[-1] == "sensorStart"
    with caplog.at_level(logging.WARNING):
        text, _ = load(TI_PROFILE, "capture")
    assert text == TI_PROFILE.read_text()
    assert not caplog.records


def test_derived_numbers_of_ti_chirp() -> None:
    numbers = derived(load(FIXTURE)[1])
    assert numbers["chirp period (us)"] == 46
    assert numbers["v max (m/s)"] == pytest.approx(20.6, abs=0.05)
    assert numbers["velocity step (m/s)"] == pytest.approx(0.322, rel=1e-2)
    assert numbers["sub-band span (m/s)"] == pytest.approx(10.3, abs=0.05)
    assert numbers["CFAR matrix (KB, max 32)"] == 16


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


@pytest.mark.parametrize(("old", "new", "message"), [
    ("[chirp]\n", "[chirp]\nidle = 7\n", "unknown key"),
    ("[chirp]\n", "[radar]\n[chirp]\n", "unknown table"),
    ("loops = 32", "", "loops"),
    ("# Chirp", 'extends = "x.toml"\n# Chirp', "unknown table \\[extends\\]"),  # no inheritance
])
def test_malformed_profile_is_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        read(write(tmp_path, "p.toml", FIXTURE.read_text().replace(old, new, 1)))


def test_extra_lines_replace_and_add_commands() -> None:
    profile = aop()
    profile["extra"]["lines"] = ["cfarCfg -1 0 2 8 4 3 0 12.0 0", "clutterRemoval -1 1", "newCmd 1"]
    cfg = parse_cfg(render(profile))
    assert cfg["cfarCfg"] == [["-1", "0", "2", "8", "4", "3", "0", "12.0", "0"]]
    assert cfg["clutterRemoval"] == [["-1", "1"]]
    assert render(profile).splitlines()[-2:] == ["newCmd 1", "sensorStart"]


def test_doppler_window_follows_the_chirp() -> None:
    assert parse_cfg(render(aop(chirp={"idle_us": 435})))["cfarFovCfg"][1] == ["-1", "1", "-2.1", "2.1"]


def test_toml_limit_violation_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="contiguous"):
        bad = FIXTURE.read_text().replace("tdm = false", "tx = [0, 2]\ntdm = false")
        load(write(tmp_path, "bad.toml", bad))


def test_cfg_limit_violation_is_a_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    text = (DATA / "points.cfg").read_text().replace("frameCfg 0 3 32 0 100", "frameCfg 0 3 32 0 5")
    with caplog.at_level(logging.WARNING):
        load(write(tmp_path, "bad.cfg", text))
    assert "frame period" in caplog.text
