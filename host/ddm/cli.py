# SPDX-License-Identifier: MIT
"""ddm: configure the AWR1843AOP DDM-MIMO raw-data firmware, capture and decode its ADC data.

A PROFILE is a TOML profile (profiles/template.toml) or a TI .cfg file, chosen by its suffix.
TOML profiles are rendered to .cfg text; .cfg files are sent as they are.
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
import time
from pathlib import Path

import numpy as np

from .cfg import chirp_axes, mimo_params, parse_cfg
from .dsp import MIN_RANGE_M, find_targets, fold, range_doppler_power, signed_doppler_bin, tx0_band
from .profile import derived, load
from .radar import CLI_PORT
from .rawdata import load_capture, save_capture

log = logging.getLogger(__name__)

CAPTURE_DIR = Path("captures")


def cmd_cfg(args: argparse.Namespace) -> None:
    """Check a profile against the hardware limits, log its derived numbers and write its .cfg text."""
    text, cfg = load(args.profile)
    for name, value in derived(cfg).items():
        log.info("%-24s %8.4g", name, value)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text)
        log.info("wrote %s", args.out)


def cmd_capture(args: argparse.Namespace) -> None:
    """Record raw ADC frames (int16 I/Q, unprocessed) through a DCA1000EVM capture card."""
    from .dca import capture, open_capture_card  # xwr loads only for the capture commands

    text, _ = load(args.profile)
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
    save_capture(out, np.stack(captured), text)
    log.info("saved %d frames of %s (chirp, rx, sample, I/Q) to %s", len(captured), captured[0].shape, out)


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

    captured, text = load_capture(args.capture)
    cfg = parse_cfg(text)
    bands, num_tx = mimo_params(cfg)
    num_chirps = captured.shape[1]
    range_step, velocity_step = chirp_axes(cfg, num_chirps)
    power = range_doppler_power(captured, 0 if bands else num_tx)
    db = 10 * np.log10(power / power.max())
    min_range_bin = int(np.ceil(MIN_RANGE_M / range_step))
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
    """Live view: the unprocessed ADC signal and its spectrum, or with --decoded the
    DDM-decoded range-velocity and top views."""
    from .view import decoded_view, raw_view

    if args.remove_static and not args.decoded:
        raise ValueError("--remove-static works only with --decoded; the raw view shows the signal as is")
    text, cfg = load(args.profile)
    if args.decoded:
        decoded_view(text, cfg, args.cli, args.remove_static)
    else:
        raw_view(text, cfg, args.cli, args.rx)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ddm", description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    verbosity = common.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="debug messages and tracebacks")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    cli_port = argparse.ArgumentParser(add_help=False, parents=[common])
    cli_port.add_argument("--cli", default=CLI_PORT, help=f"CLI port (default {CLI_PORT})")
    commands = parser.add_subparsers(title="commands", required=True, metavar="COMMAND")

    def add(handler, name: str, parents: list[argparse.ArgumentParser]) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, parents=parents or [common], help=handler.__doc__,
                                  description=handler.__doc__)
        sub.set_defaults(handler=handler)
        return sub

    sub = add(cmd_cfg, "cfg", [])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("-o", "--out", type=Path, metavar="FILE", help="write the .cfg here (default stdout)")

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
    sub.add_argument("--rx", type=int, default=0, help="RX antenna shown in the raw view (default 0)")
    sub.add_argument("--decoded", action="store_true",
                     help="processed view: Hann windows, DDM decoding, detected cells and top view")
    sub.add_argument("--remove-static", action="store_true", help="with --decoded: hide stationary objects")
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
