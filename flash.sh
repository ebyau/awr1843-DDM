#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Flash an image to the AWR1843AOPEVM over UART (board must be freshly
# powered in SOP flashing mode). Usage: ./flash.sh [image.bin] [port]
# UNIFLASH_DIR overrides the UniFlash install (default ~/ti/uniflash_9.7.0).
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
image="$(realpath "${1:-${root}/out/xwr18xx_mmw_aop_demo.bin}")"
port="${2:-/dev/ttyUSB0}"
uniflash="${UNIFLASH_DIR:-${HOME}/ti/uniflash_9.7.0}"

status=0
output="$("${uniflash}/dslite.sh" -c "${root}/awr1843aop_serial.ccxml" \
    -s "COMPort=${port}" -f "${image},1" 2>&1)" || status=$?
grep -E 'SUCCESS|error:|Failed' <<<"${output}" || printf '%s\n' "${output}"
exit "${status}"
