#!/usr/bin/env bash
# start-test.sh — try this copy of Shimmer without touching your own.
#
# As start-test.bat: runs whatever copy it sits in, as it is, on port 7870,
# with its own settings folder (~/.config/Shimmer-test unless
# SHIMMER_CONFIG_DIR is set), and with no update or branch switch.
# Everything else is start.sh's own setup.
cd "$(dirname "$0")" || exit 1
export SHIMMER_PORT="${SHIMMER_PORT:-7870}"
export SHIMMER_CONFIG_DIR="${SHIMMER_CONFIG_DIR:-$HOME/.config/Shimmer-test}"
export SHIMMER_NO_UPDATE=1
echo
echo "  TEST COPY: $(pwd)"
echo "  Port $SHIMMER_PORT, settings in $SHIMMER_CONFIG_DIR"
echo
exec bash ./start.sh "$@"
