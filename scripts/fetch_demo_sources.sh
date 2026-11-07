#!/bin/sh
# Fetch ONLY the files used for the demo reports in examples/ (single files from raw.githubusercontent.com,
# pinned to release tags). No repository is cloned. Usage: sh scripts/fetch_demo_sources.sh [dest-dir]
set -eu
DEST=${1:-scratch_demo}
get() {  # repo ref file...
    repo=$1; ref=$2; shift 2
    for f in "$@"; do
        mkdir -p "$DEST/$repo/$(dirname "$f")"
        curl -sfL "https://raw.githubusercontent.com/$repo/$ref/$f" -o "$DEST/$repo/$f" && echo "ok   $repo@$ref $f" || echo "FAIL $repo@$ref $f"
    done
}
get redis/redis 7.2.4 src/Makefile src/ae.c src/ae_epoll.c src/ae_select.c src/anet.c src/config.h src/debug.c src/util.c \
    src/server.c src/bio.c src/networking.c src/rdb.c src/syncio.c src/setcpuaffinity.c src/setproctitle.c src/atomicvar.h \
    src/cluster.c src/latency.c src/zmalloc.c src/monotonic.c src/fmacros.h
get libuv/libuv v1.48.0 CMakeLists.txt src/unix/linux.c src/unix/qnx.c src/unix/core.c src/unix/fs.c src/unix/thread.c \
    src/unix/proctitle.c src/unix/procfs-exepath.c src/unix/random-getrandom.c src/unix/sysinfo-memory.c \
    src/unix/sysinfo-loadavg.c src/unix/signal.c src/unix/process.c src/unix/posix-hrtime.c
get htop-dev/htop 3.3.0 configure.ac Makefile.am Affinity.c Compat.c linux/Platform.c linux/LinuxProcessTable.c \
    linux/LinuxMachine.c linux/LinuxProcess.c linux/SystemdMeter.c linux/LibSensors.c linux/CGroupUtils.c \
    linux/PressureStallMeter.c linux/ZramMeter.c
