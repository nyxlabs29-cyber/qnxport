#!/usr/bin/env python3
"""Check that every QNX 8.0 documentation link used by the rules resolves (HTTP 200).

Network access required. Usage:  python scripts/verify_doc_links.py
Exit code 1 if any link fails. Run before releasing a new rule set.
"""
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from qnxport.rules import ADVICE, DOCS_CHECKED, RULES  # noqa: E402


def check(url):
    req = urllib.request.Request(url, headers={"User-Agent": "qnxport-link-check"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return url, r.status
    except Exception as e:  # noqa: BLE001
        return url, str(e)


def main():
    urls = sorted({u for r in list(RULES) + list(ADVICE.values()) for _t, u in r.docs})
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(check, urls))
    bad = [(u, s) for u, s in results if s != 200]
    for u, s in results:
        print("%s %s" % (s, u))
    print("\n%d links checked, %d failed (rule data stamped %s)" % (len(urls), len(bad), DOCS_CHECKED))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
