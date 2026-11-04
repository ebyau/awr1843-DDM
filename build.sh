#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Build the raw-data firmware image (MSS and radar subsystem; no DSP code).
# Usage: ./build.sh
# Output: out/xwr18xx_mmw_demo.bin; full log: out/build.log
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${root}/env.sh"  # TI scripts are not strict-mode safe; load first
set -euo pipefail
demo="${MMWAVE_SDK_INSTALL_PATH}/ti/demo/xwr18xx/mmw"
image=xwr18xx_mmw_demo.bin
mkdir -p "${root}/out"
log="${root}/out/build.log"
: > "${log}"

make -C "${demo}" clean >> "${log}" 2>&1
make -C "${demo}" mmwDemo >> "${log}" 2>&1

cp "${demo}/${image}" "${root}/out/"
echo "Built out/${image} ($(grep -cE "^\"[^\"]+\", line [0-9]+: warning" "${log}") warnings)"
