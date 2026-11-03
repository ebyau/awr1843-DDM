# SPDX-License-Identifier: MIT
"""The ddm command: one entry point for the host tools.

Usage: uv run ddm COMMAND [ARGS...]
"""

from __future__ import annotations

import argparse
import importlib
import sys

TOOLS = {
    "points": "mmw_host",
    "heatmap": "rd_view",
    "bands": "ddm_check",
    "capture": "raw_capture",
    "decode": "ddm_raw",
    "live": "ddm_live",
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="ddm", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=TOOLS)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    tool = importlib.import_module(f"ddm.{TOOLS[args.command]}")
    sys.argv = [f"ddm {args.command}", *args.args]
    return tool.main()


if __name__ == "__main__":
    sys.exit(main())
