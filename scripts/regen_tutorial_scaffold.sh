#!/bin/sh
# Regenerates tutorial/qnx/{Makefile.qnx,qnx-toolchain-*.cmake} with qnxport itself (common + qnx loop only).
set -eu
cd "$(dirname "$0")/.."
rm -rf tutorial/build/qnx-tree && mkdir -p tutorial/build/qnx-tree
cp -r tutorial/common tutorial/qnx tutorial/build/qnx-tree/
PYTHONPATH=src python -m qnxport scaffold tutorial/build/qnx-tree --out tutorial/qnx --name evdemo
rm -rf tutorial/build
