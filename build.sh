#!/usr/bin/env bash
# Rebuild the modified datapath libraries and a demo image.
# Usage: ./build.sh [aop|std]   (default aop; std = non-AOP antenna build)
# Output: out/xwr18xx_mmw_<variant>demo.bin; full log: out/build.log
root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${root}/env.sh"  # TI scripts are not strict-mode safe; load first
set -euo pipefail
ti="${MMWAVE_SDK_INSTALL_PATH}/ti"
case "${1:-aop}" in
    aop) target=mmwAOPDemo; image=xwr18xx_mmw_aop_demo.bin ;;
    std) target=mmwDemo;    image=xwr18xx_mmw_demo.bin ;;
    *)   echo "Usage: $0 [aop|std]" >&2; exit 2 ;;
esac
mkdir -p "${root}/out"
log="${root}/out/build.log"
: > "${log}"

for lib in datapath/dpu/rangeproc datapath/dpc/dpu/dopplerproc datapath/dpc/dpu/aoa2dproc; do
    make -C "${ti}/${lib}" lib >> "${log}" 2>&1
done
make -C "${ti}/demo/xwr18xx/mmw" clean >> "${log}" 2>&1
make -C "${ti}/demo/xwr18xx/mmw" "${target}" >> "${log}" 2>&1

cp "${ti}/demo/xwr18xx/mmw/${image}" "${root}/out/"
echo "Built out/${image} ($(grep -cE "^\"[^\"]+\", line [0-9]+: warning" "${log}") warnings)"
