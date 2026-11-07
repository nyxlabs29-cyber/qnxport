#!/bin/sh
# Capture the real tool/test output that docs/tutorial-port-epoll-to-qnx8.md embeds.
# Needs: python, and (for the host test) a Linux shell with a C compiler (WSL works).
set -eu
cd "$(dirname "$0")/.."
V=tutorial/verification
mkdir -p "$V"
for d in linux portable qnx; do
    PYTHONPATH=src python -m qnxport scan "tutorial/$d" --name "tutorial/$d" --no-color --max-per-rule-text 4 > "$V/scan-$d.txt"
done
