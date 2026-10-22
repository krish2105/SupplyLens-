#!/bin/sh
set -eu
eval "$(python scripts/render/env.py)"
exec python scripts/render/predeploy.py
