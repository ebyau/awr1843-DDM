# SPDX-License-Identifier: MIT
"""Serial control of the radar: send a configuration, start and stop the sensor."""

from __future__ import annotations

import logging
import time

import serial

log = logging.getLogger(__name__)

CLI_PORT, CLI_BAUD, CLI_TIMEOUT_S = "/dev/ttyUSB0", 115200, 6.0
PROMPT = b"mmwDemo:/>"


def send_config(cli: serial.Serial, cfg_text: str) -> None:
    """Send each command line and fail fast on any reply other than 'Done'."""
    for line in cfg_text.splitlines():
        cmd = line.strip()
        if not cmd or cmd.startswith("%"):
            continue
        log.debug("> %s", cmd)
        cli.write(f"{cmd}\n".encode())
        reply = cli.read_until(PROMPT).decode(errors="replace")
        if not reply:
            raise TimeoutError(f"no reply to '{cmd}' on {cli.port}; reset the radar (NRST or power cycle)")
        if "Done" not in reply and cmd != "sensorStop":
            raise RuntimeError(f"'{cmd}' failed:\n{reply.strip()}")
        time.sleep(0.01)


def sensor_stop(cli: serial.Serial, wait: bool = False) -> None:
    """Stop the sensor; with wait, also read up to the next prompt."""
    cli.write(b"sensorStop\n")
    if wait:
        cli.read_until(PROMPT)


def open_cli(port: str) -> serial.Serial:
    return serial.Serial(port, CLI_BAUD, timeout=CLI_TIMEOUT_S)

