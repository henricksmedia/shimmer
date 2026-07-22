#!/usr/bin/env bash
# start.sh — macOS / Linux launcher for Shimmer.
#
# Mirrors start.bat: bootstraps uv, creates a private .venv, installs the
# audio libraries, then starts the server and opens a browser once it
# actually responds.  Written for bash 3.2 so it runs on stock macOS.

set -u

cd "$(dirname "$0")" || exit 1

# Port can be overridden:  SHIMMER_PORT=7870 ./start.sh
PORT="${SHIMMER_PORT:-7860}"
URL="http://localhost:$PORT"

# ── Banner ────────────────────────────────────────────────────────────
cat <<'BANNER'

     *   .        .      *          .          *   .
     ____   _   _  ___  __  __  __  __  _____  ____
    / ___| | | | ||_ _||  \/  ||  \/  || ____||  _ \
    \___ \ | |_| | | | | |\/| || |\/| ||  _|  | |_) |
     ___) ||  _  | | | | |  | || |  | || |___ |  _ <
    |____/ |_| |_||___||_|  |_||_|  |_||_____||_| \_\
       .          *                        by The Treq

    -------------------------------------------------
      de-artifact . restore . master . shine
          treqmusic.com/tools/shimmer
    -------------------------------------------------

BANNER

# ── Step 1: uv ────────────────────────────────────────────────────────
# uv manages an isolated .venv and downloads the right Python itself, so
# it is the only prerequisite.
add_local_bin_to_path() {
    for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        if [ -x "$candidate/uv" ]; then
            PATH="$candidate:$PATH"
            export PATH
            return 0
        fi
    done
    return 1
}

if ! command -v uv >/dev/null 2>&1; then
    add_local_bin_to_path || true
fi

if ! command -v uv >/dev/null 2>&1; then
    echo " FIRST-TIME SETUP"
    echo " ----------------"
    echo " Shimmer needs a free tool called \"uv\" to install itself."
    echo " It handles Python and all the audio libraries for you."
    echo
    printf 'Install uv now? [Y/n]: '
    read -r reply
    case "$reply" in
        [Nn]*)
            echo
            echo " To install uv manually:"
            echo "     curl -LsSf https://astral.sh/uv/install.sh | sh"
            echo " Or with Homebrew:  brew install uv"
            echo " Docs: https://docs.astral.sh/uv/getting-started/installation/"
            echo
            echo " Then run ./start.sh again."
            exit 1
            ;;
    esac

    echo
    if command -v brew >/dev/null 2>&1; then
        echo " Installing uv with Homebrew..."
        brew install uv
    else
        echo " Installing uv from astral.sh..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    echo

    # Installers drop uv in ~/.local/bin, which the current shell may not
    # have on PATH yet.
    if ! command -v uv >/dev/null 2>&1; then
        add_local_bin_to_path || true
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo " uv was installed but this shell cannot see it yet."
        echo " Open a new terminal and run ./start.sh again."
        exit 0
    fi
fi

# ── Step 2: local environment ─────────────────────────────────────────
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
    echo " Creating a local Python environment..."
    echo " (first run only - this may take a few minutes)"
    echo
    if ! uv venv; then
        echo
        echo " ERROR: could not create the environment."
        echo " Check your internet connection and try again."
        exit 1
    fi
fi

# ── Step 3: dependencies ──────────────────────────────────────────────
# Probe imports rather than trusting a sentinel file — a real import test
# is the only way to know the venv actually has what we need.
if ! "$PY" -c "import fastapi, uvicorn, numpy, scipy, soundfile, pyloudnorm" >/dev/null 2>&1; then
    echo " Installing audio libraries..."
    echo " (first run only - about 200 MB, a few minutes)"
    echo
    # --python targets this project's venv explicitly; without it uv has to
    # infer the environment and can pick the wrong one.
    uv pip install --python "$PY" -r requirements.txt || true

    # Verify by importing rather than trusting the exit code — that is the
    # only thing that proves the environment is actually usable.
    if ! "$PY" -c "import fastapi, uvicorn, numpy, scipy, soundfile, pyloudnorm" >/dev/null 2>&1; then
        echo
        echo " ERROR: the audio libraries did not install correctly."
        echo
        echo " The real reason is in the messages above — please scroll up."
        echo " Common causes are no internet connection, a company proxy or"
        echo " antivirus blocking downloads, or low disk space."
        echo
        echo " To save a log for a bug report, run this in the same folder"
        echo " and attach setup-log.txt to your issue:"
        echo
        echo "     uv pip install --python .venv/bin/python -r requirements.txt > setup-log.txt 2>&1"
        echo
        echo "     https://github.com/henricksmedia/shimmer/issues"
        echo
        exit 1
    fi
    echo
    echo " Setup complete. Future launches start in seconds."
    echo
fi

# ── Step 4: free the port ─────────────────────────────────────────────
port_busy() {
    if command -v lsof >/dev/null 2>&1; then
        [ -n "$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)" ]
    else
        return 1   # cannot tell; let the bind decide
    fi
}

if command -v lsof >/dev/null 2>&1; then
    OLD_PIDS=$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$OLD_PIDS" ]; then
        echo " Closing previous session..."
        # shellcheck disable=SC2086
        kill $OLD_PIDS 2>/dev/null || true
        # Wait for the socket to actually release — kill returns before the
        # OS tears it down, and binding too early fails cryptically.
        for _ in $(seq 1 40); do
            port_busy || break
            sleep 0.25
        done
        # shellcheck disable=SC2086
        port_busy && kill -9 $OLD_PIDS 2>/dev/null || true
        for _ in $(seq 1 20); do
            port_busy || break
            sleep 0.25
        done
    fi

    if port_busy; then
        echo
        echo " ERROR: port $PORT is still in use and could not be freed."
        echo
        echo " Find out what is holding it:"
        echo "     lsof -i :$PORT"
        echo
        echo " Or start Shimmer on a different port:"
        echo "     SHIMMER_PORT=7870 ./start.sh"
        echo
        exit 1
    fi
fi

# ── Step 5: start, then open the browser once it responds ─────────────
open_browser() {
    if command -v open >/dev/null 2>&1; then
        open "$URL"                      # macOS
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1  # Linux
    fi
}

# Poll rather than guessing a delay: on a cold start the server can take
# several seconds to import numpy/scipy, and opening the browser too early
# lands the user on a connection-error page.
(
    for _ in $(seq 1 90); do
        if curl -fsS --max-time 2 "$URL" >/dev/null 2>&1; then
            open_browser
            break
        fi
        sleep 0.5
    done
) &
POLLER_PID=$!

cleanup() {
    kill "$POLLER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo " Starting Shimmer..."
echo " $URL"
echo
echo " Leave this window open while you work. Press Ctrl+C to stop Shimmer."
echo

"$PY" -m uvicorn shimmer.server:app --host 127.0.0.1 --port "$PORT" --log-level warning
