# SPDX-License-Identifier: MIT
"""ddm: configure the AWR1843AOP DDM-MIMO raw-data firmware, capture and view its ADC data.

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

from .cfg import describe_mode, parse_cfg
from .profile import derived, load
from .radar import CLI_PORT
from .rawdata import load_capture, save_capture

log = logging.getLogger(__name__)

CAPTURE_DIR = Path("captures")


def cmd_cfg(args: argparse.Namespace) -> None:
    """Check a profile against the hardware limits, log its derived numbers and write its .cfg text."""
    text, cfg = load(args.profile, args.tdm)
    log.info("mode: %s", describe_mode(cfg))
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

    text, cfg = load(args.profile, args.tdm)
    log.info("mode: %s", describe_mode(cfg))
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
    complete = [frame.complete for frame in captured]
    save_capture(out, np.stack([frame.iq for frame in captured]), text, complete,
                 [frame.timestamp for frame in captured])
    if not all(complete):
        log.warning("%d of %d frames are incomplete (zero-filled, marked in the capture)",
                    complete.count(False), len(captured))
    log.info("saved %d frames of %s (chirp, rx, sample, I/Q) to %s", len(captured), captured[0].iq.shape, out)


def cmd_show(args: argparse.Namespace) -> None:
    """Replay a capture's raw spectrum in a loop, or save its first frame as an image."""
    from .view import replay, snapshot

    cap = load_capture(args.capture)
    cfg, frames = parse_cfg(cap.config), cap.frames
    log.info("%d frames of %s (chirp, rx, sample), %s, format %s", len(frames), frames.shape[1:],
             describe_mode(cfg), cap.meta["format"])
    if not cap.complete.all():
        log.warning("%d incomplete frames (zero-filled): %s", (~cap.complete).sum(),
                    np.flatnonzero(~cap.complete).tolist())
    if args.snapshot is not None:
        snapshot(frames[0], cfg, args.snapshot)
        log.info("saved %s", args.snapshot)
    else:
        replay(frames, cfg)


def cmd_live(args: argparse.Namespace) -> None:
    """Live unwindowed range-Doppler spectrum of RX 0."""
    from .view import live_view

    text, cfg = load(args.profile, args.tdm)
    log.info("mode: %s", describe_mode(cfg))
    live_view(text, cfg, args.cli)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ddm", description=__doc__.splitlines()[0])
    common = argparse.ArgumentParser(add_help=False)
    verbosity = common.add_mutually_exclusive_group()
    verbosity.add_argument("-v", "--verbose", action="store_true", help="debug messages and tracebacks")
    verbosity.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")
    cli_port = argparse.ArgumentParser(add_help=False, parents=[common])
    cli_port.add_argument("--cli", default=CLI_PORT, help=f"CLI port (default {CLI_PORT})")
    tdm = argparse.ArgumentParser(add_help=False)
    tdm.add_argument("--tdm", action="store_true",
                     help="allow a .cfg file without ddmCfg, which runs TDM (one TX per chirp)")
    commands = parser.add_subparsers(title="commands", required=True, metavar="COMMAND")

    def add(handler, name: str, parents: list[argparse.ArgumentParser]) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, parents=parents or [common], help=handler.__doc__,
                                  description=handler.__doc__)
        sub.set_defaults(handler=handler)
        return sub

    sub = add(cmd_cfg, "cfg", [common, tdm])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("-o", "--out", type=Path, metavar="FILE", help="write the .cfg here (default stdout)")

    sub = add(cmd_capture, "capture", [cli_port, tdm])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
    sub.add_argument("-n", "--frames", type=int, default=50, help="frames to record (default 50)")
    sub.add_argument("-o", "--out", type=Path, metavar="FILE",
                     help=f"output .npz (default {CAPTURE_DIR}/YYYYmmdd-HHMMSS_<profile>.npz)")

    sub = add(cmd_show, "show", [])
    sub.add_argument("capture", type=Path, metavar="CAPTURE.npz")
    sub.add_argument("--snapshot", type=Path, metavar="PNG", help="save the first frame's plot to this PNG")

    sub = add(cmd_live, "live", [cli_port, tdm])
    sub.add_argument("profile", type=Path, metavar="PROFILE")
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
