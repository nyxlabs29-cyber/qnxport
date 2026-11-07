#!/bin/sh
# Regenerate examples/ from sources fetched by fetch_demo_sources.sh.  Usage: sh scripts/run_examples.sh [src-dir]
set -eu
cd "$(dirname "$0")/.."
SRC=${1:-scratch_demo}
run() {  # name repo
    name=$1; repo=$2
    mkdir -p "examples/$name"
    PYTHONPATH=src python -m qnxport scan "$SRC/$repo" --name "$name" --no-color --out-dir "examples/$name" --max-per-rule 25 \
        --max-per-rule-text 3 > "examples/$name/terminal.txt"
}
run redis-7.2.4 redis/redis
run libuv-v1.48.0 libuv/libuv
run htop-3.3.0 htop-dev/htop
PYTHONPATH=src python -m qnxport scaffold "$SRC/redis/redis" --name redis --out examples/redis-7.2.4/scaffold >/dev/null
