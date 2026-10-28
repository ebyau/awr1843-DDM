#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Load the mmWave SDK build environment for this project (AWR1843 target).
# Usage: source ~/DDM/env.sh
cd "$(dirname "${BASH_SOURCE[0]}")/sdk/packages/scripts/unix" && source ./setenv.sh > /dev/null
cd - > /dev/null
