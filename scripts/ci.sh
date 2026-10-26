#!/usr/bin/env bash
# What CI runs (.github/workflows/ci.yml), and the same on your computer:
#
#   scripts/ci.sh                                  unit tests, the EDA base image, Docker tests, E2E suites
#   STAGES="unit docker" scripts/ci.sh             only some stages (unit, image, docker, e2e)
#   SUITES="smoke_home lint_sim" scripts/ci.sh     only some E2E suites
#
# The ASIC and analog tests need the IIC-OSIC-TOOLS image (17 GB, more than a CI runner's disk):
# without it they skip themselves, so CI runs everything else. The ams_corners and xschem_desktop
# suites need that image too and are left out of the default list (SUITES="ams_corners
# xschem_desktop" where the image is). The E2E suites start their own server on
# FRONTEND_PORT/BACKEND_PORT (3000/8000 unless set): pick free ones on a shared computer.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

STAGES="${STAGES:-unit image docker e2e}"
SUITES="${SUITES:-smoke_home collab_live offline_lan lint_sim ai_review fpga_build permissions signoff_release board_helper lab_package phone_view}"
OUT="${CI_OUTPUT:-$PWD/ci-output}"
has() { [[ " $STAGES " == *" $1 "* ]]; }
step() { echo; echo "=== $* ==="; }

if has unit; then
  step "unit and integration tests"
  poetry run pytest -m "not docker" -q
fi
if has image; then
  step "the EDA base image"
  docker image inspect chipova/eda-base:1 >/dev/null 2>&1 || docker build -t chipova/eda-base:1 infra/dockerfiles/eda-base
fi
if has docker; then
  step "tests in containers"
  poetry run pytest -m docker -q -rs
fi
if has e2e; then
  for suite in $SUITES; do
    step "E2E $suite"
    OUTPUT_DIR="$OUT/$suite" ./run_test_suite.sh "$suite"
  done
fi
echo; echo "CI: all stages passed ($STAGES)"
