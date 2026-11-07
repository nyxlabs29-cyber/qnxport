#!/usr/bin/env python3
"""Expand <!-- include: path --> markers in README.src.md and docs/*.src.md into fenced code blocks (keeps the tutorial in sync with the code).

Usage: python scripts/build_docs.py
"""
import glob
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LANG = {".c": "c", ".h": "c", ".txt": "text", ".sh": "sh", ".cmake": "cmake", ".qnx": "make", ".yml": "yaml", ".md": "markdown"}


def expand(match):
    rel = match.group(1).strip()
    path = os.path.join(ROOT, rel)
    with open(path, encoding="utf-8") as fh:
        body = fh.read().rstrip("\n")
    ext = os.path.splitext(rel)[1]
    lang = "make" if rel.endswith("Makefile.qnx") else LANG.get(ext, "")
    return "```%s\n%s\n```\n*(file: `%s`)*" % (lang, body, rel)


for src in glob.glob(os.path.join(ROOT, "docs", "*.src.md")) + [os.path.join(ROOT, "README.src.md")]:
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    out = re.sub(r"<!-- include: (.+?) -->", expand, text)
    dst = src.replace(".src.md", ".md")
    with open(dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    print("wrote", os.path.relpath(dst, ROOT))
