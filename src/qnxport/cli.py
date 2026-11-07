"""Command line interface: qnxport scan | scaffold | rules | explain | init-ci."""

import argparse
import os
import sys
import textwrap
from typing import List, Optional

from . import __version__
from .generators import GITHUB_ACTION, write_scaffold
from .report import project_name, render_json, render_markdown, render_text
from .rules import RULE_BY_ID, RULES, ADVICE, SEVERITY_ORDER, DOCS_CHECKED
from .sarif import render_sarif
from .scanner import scan_path

COMMANDS = {"scan", "scaffold", "rules", "explain", "init-ci"}


def _write(path: str, text: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _scan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("path", help="project directory (or a single file) to scan")
    p.add_argument("--name", default="", help="project label used in reports (default: directory name)")
    p.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                   help="skip files whose relative path or name matches GLOB (repeatable)")
    p.add_argument("--ignore", action="append", default=[], metavar="RULE", help="disable a rule id, e.g. QNX020 (repeatable)")


def cmd_scan(a: argparse.Namespace) -> int:
    if not os.path.exists(a.path):
        print("qnxport: no such path: %s" % a.path, file=sys.stderr)
        return 2
    bad = [r for r in a.ignore if r not in RULE_BY_ID]
    if bad:
        print("qnxport: unknown rule id(s): %s (see: qnxport rules)" % ", ".join(bad), file=sys.stderr)
        return 2
    res = scan_path(a.path, a.exclude, a.ignore)
    name = project_name(res, a.name)
    if a.out_dir:
        a.md = a.md or os.path.join(a.out_dir, "qnxport-report.md")
        a.json = a.json or os.path.join(a.out_dir, "qnxport-report.json")
        a.sarif = a.sarif or os.path.join(a.out_dir, "qnxport-report.sarif")
    if a.md:
        _write(a.md, render_markdown(res, name, a.max_per_rule))
    if a.json:
        _write(a.json, render_json(res, name))
    if a.sarif:
        _write(a.sarif, render_sarif(res))
    if not a.quiet:
        color = sys.stdout.isatty() and not a.no_color and not os.environ.get("NO_COLOR")
        sys.stdout.write(render_text(res, name, color=color, max_per_rule=a.max_per_rule_text, brief=a.brief))
        for label, path in (("markdown", a.md), ("json", a.json), ("sarif", a.sarif)):
            if path:
                print("wrote %-8s %s" % (label, path))
    else:
        for label, path in (("markdown", a.md), ("json", a.json), ("sarif", a.sarif)):
            if path:
                print("wrote %s: %s" % (label, path))
    if a.fail_on != "never":
        thr = SEVERITY_ORDER[a.fail_on]
        n = sum(1 for f in res.findings if SEVERITY_ORDER[f.severity] <= thr)
        if n:
            print("qnxport: %d finding(s) at or above '%s' (use // qnxport:ignore RULE or --ignore to accept)" % (n, a.fail_on),
                  file=sys.stderr)
            return 1
    return 0


def cmd_scaffold(a: argparse.Namespace) -> int:
    if not os.path.isdir(a.path):
        print("qnxport: not a directory: %s" % a.path, file=sys.stderr)
        return 2
    res = scan_path(a.path, a.exclude, [])
    name = project_name(res, a.name)
    out = a.out or os.path.join(a.path, "qnx")
    for p in write_scaffold(res, out, name, a.arch):
        print("wrote %s" % p)
    print("These files are starters: check them against your QNX SDP 8.0 install before use.")
    return 0


def cmd_rules(a: argparse.Namespace) -> int:
    allr = list(RULES) + list(ADVICE.values())
    if a.format == "markdown":
        print("# qnxport rules\n")
        print("QNX 8.0 documentation cross-checked on %s. Confidence `documented` = the QNX 8.0 docs page for the "
              "replacement exists and states the behaviour used; `verify` = likely strategy, confirm on your SDP.\n" % DOCS_CHECKED)
        print("| ID | Sev | Confidence | Category | Detects / strategy |")
        print("|---|---|---|---|---|")
        for r in allr:
            print("| %s | %s | %s | %s | **%s.** %s |" % (r.id, r.severity, r.confidence, r.category, r.title,
                                                         r.qnx.replace("|", "/")))
        print("\n## Documentation links per rule\n")
        for r in allr:
            if r.docs:
                print("- **%s**: %s" % (r.id, "; ".join("[%s](%s)" % (t, u) for t, u in r.docs)))
    else:
        for r in allr:
            print("%s  %-6s %-10s %s" % (r.id, r.severity, r.confidence, r.title))
    return 0


def cmd_explain(a: argparse.Namespace) -> int:
    r = RULE_BY_ID.get(a.rule.upper())
    if not r:
        print("qnxport: unknown rule %s" % a.rule, file=sys.stderr)
        return 2
    print("%s  %s  [%s, %s]" % (r.id, r.title, r.severity, r.confidence))
    print(textwrap.fill("Why: " + r.why, 100))
    print(textwrap.fill("QNX 8.0: " + r.qnx, 100))
    for t, u in r.docs:
        print("  %s\n    %s" % (t, u))
    return 0


def cmd_init_ci(a: argparse.Namespace) -> int:
    if a.out:
        _write(a.out, GITHUB_ACTION)
        print("wrote %s" % a.out)
    else:
        sys.stdout.write(GITHUB_ACTION)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="qnxport", description="Host-side porting assistant: finds what to change to run a "
                                                           "C/C++ Linux/POSIX project on QNX 8.0.")
    p.add_argument("--version", action="version", version="qnxport " + __version__)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="scan a project and write reports")
    _scan_args(s)
    s.add_argument("--md", metavar="FILE", help="write the Markdown report")
    s.add_argument("--json", metavar="FILE", help="write the JSON report")
    s.add_argument("--sarif", metavar="FILE", help="write the SARIF 2.1.0 report (GitHub code scanning)")
    s.add_argument("--out-dir", metavar="DIR", help="write qnxport-report.{md,json,sarif} into DIR")
    s.add_argument("--fail-on", choices=["high", "medium", "low", "info", "never"], default="never",
                   help="exit 1 if a finding at this severity or worse exists (default: never)")
    s.add_argument("--quiet", "-q", action="store_true", help="no terminal summary")
    s.add_argument("--brief", action="store_true", help="terminal summary table only")
    s.add_argument("--no-color", action="store_true")
    s.add_argument("--max-per-rule", type=int, default=15, help="locations per rule in the Markdown report (default 15)")
    s.add_argument("--max-per-rule-text", type=int, default=3, help="locations per rule in the terminal (default 3)")
    s.set_defaults(fn=cmd_scan)

    g = sub.add_parser("scaffold", help="write a starter QNX build scaffold (Makefile.qnx + CMake toolchain files)")
    g.add_argument("path", help="project directory")
    g.add_argument("--out", metavar="DIR", help="output directory (default: <path>/qnx)")
    g.add_argument("--arch", choices=["aarch64le", "x86_64", "both"], default="both")
    g.add_argument("--name", default="")
    g.add_argument("--exclude", action="append", default=[], metavar="GLOB")
    g.set_defaults(fn=cmd_scaffold)

    r = sub.add_parser("rules", help="list all rules")
    r.add_argument("--format", choices=["text", "markdown"], default="text")
    r.set_defaults(fn=cmd_rules)

    e = sub.add_parser("explain", help="explain one rule, with QNX 8.0 doc links")
    e.add_argument("rule")
    e.set_defaults(fn=cmd_explain)

    c = sub.add_parser("init-ci", help="print (or write) the example GitHub Actions workflow")
    c.add_argument("--out", metavar="FILE")
    c.set_defaults(fn=cmd_init_ci)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in COMMANDS and not argv[0].startswith("-"):
        argv.insert(0, "scan")      # shorthand: qnxport PATH
    p = build_parser()
    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
