# SPDX-License-Identifier: MIT
"""ddm: configure the AWR1843AOP DDM-MIMO firmware and decode its output.

A PROFILE is a TOML profile (profiles/template.toml) or a TI .cfg file, chosen by its suffix.
TOML profiles get the outputs the command needs; .cfg files are sent as they are.
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
import time
from pathlib import Path

import numpy as np

from .cfg import chirp_axes, ddm_params, mimo_params, min_range_m, parse_cfg, range_axis
from .dsp import find_targets, fold, range_doppler_power, signed_doppler_bin, tx0_band
from .frames import HEATMAP_Q8_TO_DB, TLV_RANGE_DOPPLER, frames
from .plotting import centre_bands
from .profile import OUTPUTS, derived, load
from .radar import CLI_PORT, DATA_PORT, running_radar

log = logging.getLogger(__name__)

CAPTURE_DIR = Path("captures")


def cmd_cfg(args: argparse.Namespace) -> None:
    """Check a profile against the hardware limits, log its derived numbers and write its .cfg text."""
    text, cfg = load(args.profile, args.use)
    for name, value in derived(cfg).items():
        log.info("%-24s %8.4g", name, value)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text)
        log.info("wrote %s", args.out)


def cmd_points(args: argparse.Namespace) -> None:
    """Configure the radar and print a point-cloud summary per frame."""
    text, _ = load(args.profile, "points")
    with running_radar(text, args.cli, args.data) as data:
        for frame in itertools.islice(frames(data), args.frames):
            nearest = min(frame.points, key=lambda p: p.x**2 + p.y**2, default=None)
            summary = (f"nearest ({nearest.x:+.2f}, {nearest.y:+.2f}, {nearest.z:+.2f}) m, "
                       f"v={nearest.v:+.2f} m/s") if nearest else "no points"
            print(f"frame {frame.number:5d}: {len(frame.points):3d} points, {summary}")


def cmd_heatmap(args: argparse.Namespace) -> None:
    """Live range-Doppler heat map from the firmware, with the sub-band boundaries marked."""
    from .view import heatmap_view  # matplotlib loads only for the commands that plot

    text, cfg = load(args.profile, "heatmap")
    bands = ddm_params(cfg)[0] if args.bands is None else args.bands
    heatmap_view(text, cfg, bands, args.cli, args.data, args.snapshot)


def band_levels_db(heatmap: np.ndarray, bands: int) -> np.ndarray:
    """Peak level per Doppler sub-band at the strongest range bin, in dB.

    The sub-bands are centred on their static-target copies, as in the plots: a
    static target sits on a band edge, so its Doppler spill would otherwise count
    as the neighbouring (empty) band.
    """
    row = heatmap[np.argmax(heatmap.max(axis=1))]
    return centre_bands(row[None, :], bands)[0].reshape(bands, -1).max(axis=1) * HEATMAP_Q8_TO_DB


def cmd_bands(args: argparse.Namespace) -> None:
    """Print the level of each Doppler sub-band at the strongest range bin (static scene)."""
    text, cfg = load(args.profile, "heatmap")
    num_range_bins, _ = range_axis(cfg)
    bands = ddm_params(cfg)[0] if args.bands is None else args.bands
    if bands < 2:
        raise ValueError("the configuration has no ddmCfg; pass --bands")
    with running_radar(text, args.cli, args.data) as data:
        for frame in itertools.islice(frames(data), args.frames):
            raw = frame.tlvs.get(TLV_RANGE_DOPPLER)
            if raw is None:
                log.warning("frame %d: no range-Doppler heat map TLV", frame.number)
                continue
            heatmap = np.frombuffer(raw, dtype="<u2").reshape(num_range_bins, -1)
            levels = band_levels_db(heatmap.astype(float), bands)
            rel = levels - levels.max()
            text = "  ".join(f"band{i}: {r:6.1f} dB" for i, r in enumerate(rel))
            print(f"frame {frame.number:4d} ({heatmap.shape[1]} Doppler bins): {text}")


def cmd_capture(args: argparse.Namespace) -> None:
    """Record raw ADC frames through a DCA1000EVM capture card."""
    from .dca import capture, open_capture_card  # xwr loads only for the capture commands

    text, _ = load(args.profile, "capture")
    out = args.out or CAPTURE_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}_{args.profile.stem}.npz"
    stream = capture(text, args.cli, open_capture_card())
    try:
        captured = list(itertools.islice(stream, args.frames))
    finally:
        stream.close()
    if not captured:
        raise TimeoutError("no frames received; check the LVDS cable and capture card")
    if len(captured) < args.frames:
        log.warning("stream timed out after %d of %d frames", len(captured), args.frames)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, frames=np.stack(captured), config=text)
    log.info("saved %d frames of %s (chirp, rx, sample) to %s", len(captured), captured[0].shape, out)


def print_ddm_targets(power: np.ndarray, bands: int, num_tx: int, min_range_bin: int,
                      range_step: float, velocity_step: float) -> None:
    """The strongest targets of a DDM range-Doppler map with their sub-band levels."""
    num_chirps = power.shape[1]
    width = num_chirps // bands
    print(" range(m)  v(m/s)  TX0  " + "  ".join(f"band{b}(dB)" for b in range(bands))
          + "  weakest TX - mean spare (dB)")
    for range_bin, folded_bin in find_targets(fold(power, bands), min_range_bin):
        band_power = power[range_bin, folded_bin::width]
        tx0 = int(tx0_band(band_power, num_tx))
        tx_bands = [(tx0 + k) % bands for k in range(num_tx)]
        spare = np.delete(band_power, tx_bands)
        margin_db = 10 * np.log10(band_power[tx_bands].min() / spare.mean())
        signed_bin = signed_doppler_bin(folded_bin, tx0, width, num_chirps)
        levels = 10 * np.log10(band_power / band_power.max())
        print(f"{range_bin * range_step:9.2f} {signed_bin * velocity_step:7.2f} {tx0:4d}  "
              + "  ".join(f"{level:10.1f}" for level in levels) + f"  {margin_db:28.1f}")


def cmd_decode(args: argparse.Namespace) -> None:
    """Decode a raw DDM or TDM capture: range-Doppler map and the strongest targets."""
    import matplotlib.pyplot as plt

    from .plotting import draw_axes

    data = np.load(args.capture)
    captured, cfg = data["frames"], parse_cfg(str(data["config"]))
    bands, num_tx = mimo_params(cfg)
    num_chirps = captured.shape[1]
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    power = range_doppler_power(captured, 0 if bands else num_tx)
    db = 10 * np.log10(power / power.max())
    min_range_bin = int(np.ceil(min_range_m(cfg) / range_step))
    log.info("%d %s frames; %.3f m and %.3f m/s per bin", len(captured), "DDM" if bands else "TDM",
             range_step, velocity_step)
    if bands:
        print_ddm_targets(power, bands, num_tx, min_range_bin, range_step, velocity_step)
    else:
        print(" range(m)  v(m/s)  level(dB)")
        for range_bin, doppler_bin in find_targets(db, min_range_bin):
            velocity = signed_doppler_bin(doppler_bin, 0, 0, power.shape[1]) * velocity_step
            print(f"{range_bin * range_step:9.2f} {velocity:7.2f} {db[range_bin, doppler_bin]:10.1f}")

    fig, ax = plt.subplots(figsize=(9, 6), layout="constrained")
    image = draw_axes(ax, db, range_step, bands, f"Raw-data range-Doppler map, {len(captured)} frames")
    fig.colorbar(image, ax=ax, label="Level relative to peak (dB)", shrink=0.8)
    if args.snapshot is not None:
        fig.savefig(args.snapshot, dpi=120)
        log.info("saved %s", args.snapshot)
    else:
        plt.show()


def cmd_live(args: argparse.Namespace) -> None:
    """Live raw-data view: raw range-Doppler, DDM-decoded range-velocity and top view."""
    from .view import live_view

    text, cfg = load(args.profile, "capture")
    live_view(text, cfg, args.cli, args.remove_static)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ddm", description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    verbosity = common.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="debug messages and tracebacks")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    cli_port = argparse.ArgumentParser(add_help=False, parents=[common])
    cli_port.add_argument("--cli", default=CLI_PORT, help=f"CLI port (default {CLI_PORT})")
    ports = argparse.ArgumentParser(add_help=False, parents=[cli_port])
    ports.add_argument("--data", default=DATA_PORT, help=f"data port (default {DATA_PORT})")
    commands = parser.add_subparsers(title="commands", required=True, metavar="COMMAND")

    def add(handler, name: str, parents: list[argparse.ArgumentParser]) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, parents=parents or [common], help=handler.__doc__,
                                  description=handler.__doc__)
        sub.set_defaults(handler=handler)
        return sub

    sub = add(cmd_cfg, "cfg", [])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("--for", dest="use", choices=OUTPUTS, default="capture",
                     help="outputs of the command the profile is for (default capture)")
    sub.add_argument("-o", "--out", type=Path, metavar="FILE", help="write the .cfg here (default stdout)")

    sub = add(cmd_points, "points", [ports])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("--frames", type=int, default=10, help="frames to print (default 10)")

    sub = add(cmd_heatmap, "heatmap", [ports])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("--bands", type=int, help="sub-band markers (default: ddmCfg; 0: none)")
    sub.add_argument("--snapshot", type=Path, metavar="PNG", help="save one frame to this PNG and exit")

    sub = add(cmd_bands, "bands", [ports])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("--bands", type=int, help="sub-bands (default: ddmCfg)")
    sub.add_argument("--frames", type=int, default=5, help="frames to print (default 5)")

    sub = add(cmd_capture, "capture", [cli_port])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("-n", "--frames", type=int, default=50, help="frames to record (default 50)")
    sub.add_argument("-o", "--out", type=Path, metavar="FILE",
                     help=f"output .npz (default {CAPTURE_DIR}/YYYYmmdd-HHMMSS_<profile>.npz)")

    sub = add(cmd_decode, "decode", [])
    sub.add_argument("capture", type=Path, metavar="CAPTURE.npz")
    sub.add_argument("--snapshot", type=Path, metavar="PNG", help="save the range-Doppler map to this PNG")

    sub = add(cmd_live, "live", [cli_port])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("--remove-static", action="store_true", help="hide stationary objects")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s", stream=sys.stderr)
    try:
        args.handler(args)
    # OSError covers TimeoutError, serial.SerialException and missing files;
    # TypeError covers wrongly typed profile values.
    except (ValueError, TypeError, RuntimeError, OSError) as err:
        log.error("%s", err, exc_info=args.verbose)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
