#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Flash an image to the AWR1843AOPEVM over UART (board must be freshly
# powered in SOP flashing mode). Usage: ./flash.sh [image.bin] [port]
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
image="$(realpath "${1:-${root}/out/xwr18xx_mmw_aop_demo.bin}")"
port="${2:-/dev/ttyUSB0}"

"${HOME}/ti/uniflash_9.7.0/dslite.sh" -c "${root}/awr1843aop_serial.ccxml" \
    -s "COMPort=${port}" -f "${image},1" 2>&1 \
    | grep -E 'SUCCESS|error:|Failed' || true
