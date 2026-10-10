#!/bin/sh
# Run Sherlock from this source tree. No install required.
set -e
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"
exec python3 -m sherlock "$@"
