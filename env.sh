#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Load the mmWave SDK build environment for this project (AWR1843 target).
# Usage: source ~/DDM/env.sh
pushd "$(dirname "${BASH_SOURCE[0]}")/sdk/packages/scripts/unix" > /dev/null || return
source ./setenv.sh > /dev/null
popd > /dev/null || return
