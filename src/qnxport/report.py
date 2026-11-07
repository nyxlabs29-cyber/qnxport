"""Report renderers: terminal text, Markdown and JSON."""

import json
import os
import textwrap
from collections import Counter, OrderedDict
from typing import Dict, List

from . import __version__
from .rules import DOCS_CHECKED, RULE_BY_ID, SEVERITY_ORDER
from .scanner import Finding, ScanResult

SEV_LABEL = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW", "info": "INFO"}
SEV_COLOR = {"high": "31", "medium": "33", "low": "36", "info": "90"}
CONF_TEXT = {"documented": "documented in QNX 8.0 docs", "verify": "VERIFY on your SDP"}

LIMITATIONS = (
    "qnxport is a static, pattern-based scan (comments and string literals are understood; no compiler or "
    "preprocessor run). It lists the places that need attention and a porting strategy backed by the public "
    "QNX 8.0 documentation. It cannot prove that a project builds or behaves correctly on QNX: compile with qcc, "
    "run on a QNX 8.0 target and test. Findings marked 'verify' name a likely strategy that could not be confirmed "
    "from the public documentation; check them against the headers and docs of your installed QNX SDP. "
    "'Not in the QNX 8.0 C Library Reference' means no page was found for the function, not that the symbol is absent "
    "from your SDP."
)


def project_name(res: ScanResult, name: str = "") -> str:
    return name or os.path.basename(res.root.rstrip("/\\")) or "project"


def summarize(res: ScanResult) -> dict:
    sev = Counter(f.severity for f in res.findings)
    base = Counter(f.base_severity for f in res.findings)
    rules: Dict[str, dict] = OrderedDict()
    for f in res.findings:
        e = rules.setdefault(f.rule_id, {"count": 0, "files": set(), "worst": f.severity})
        e["count"] += 1
        e["files"].add(f.path)
        if SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[e["worst"]]:
            e["worst"] = f.severity
    by_file = Counter(f.path for f in res.findings if f.severity in ("high", "medium"))
    return {
        "by_severity": {k: sev.get(k, 0) for k in ("high", "medium", "low", "info")},
        "by_base_severity": {k: base.get(k, 0) for k in ("high", "medium", "low", "info")},
        "total": len(res.findings),
        "rules_triggered": len(rules),
        "rules": {k: {"count": v["count"], "files": len(v["files"]), "worst_severity": v["worst"]} for k, v in rules.items()},
        "top_files": [{"file": p, "high_medium_findings": n} for p, n in by_file.most_common(10)],
    }


def _group(findings: List[Finding]) -> Dict[str, List[Finding]]:
    g: Dict[str, List[Finding]] = OrderedDict()
    for f in findings:
        g.setdefault(f.rule_id, []).append(f)
    # order rules by worst severity then count
    return OrderedDict(sorted(g.items(), key=lambda kv: (min(SEVERITY_ORDER[x.severity] for x in kv[1]), -len(kv[1]), kv[0])))


def _scope_line(res: ScanResult, name: str) -> str:
    return "%s: %d source files, %s lines, %d build files" % (
        name, len(res.source_files), format(res.loc, ","), len(res.build_files))


def _c(txt: str, code: str, color: bool) -> str:
    return "\033[%sm%s\033[0m" % (code, txt) if color else txt


# --------------------------------------------------------------------------
def render_text(res: ScanResult, name: str = "", color: bool = False, max_per_rule: int = 3, brief: bool = False) -> str:
    name = project_name(res, name)
    s = summarize(res)
    sv = s["by_severity"]
    out: List[str] = []
    out.append("qnxport %s - QNX 8.0 porting scan" % __version__)
    out.append("scanned  " + _scope_line(res, name))
    if res.qnx_aware_files:
        out.append("note     %d file(s) already mention __QNX__/__QNXNTO__ (existing QNX support?): %s" % (
            len(res.qnx_aware_files), ", ".join(res.qnx_aware_files[:4]) + (" ..." if len(res.qnx_aware_files) > 4 else "")))
    out.append("findings %s high | %s medium | %s low | %s info (info = already inside a Linux-only #if branch, or advice)  [%d rules, %d findings]" % (
        _c(str(sv["high"]), "31;1", color), _c(str(sv["medium"]), "33;1", color), sv["low"], sv["info"],
        s["rules_triggered"], s["total"]))
    if not res.findings:
        out.append("\nNo Linux-specific constructs from the rule set were found.")
        return "\n".join(out) + "\n"
    out.append("")
    out.append("%-7s %-7s %-6s %-6s %s" % ("SEV", "RULE", "COUNT", "FILES", "WHAT"))
    for rid, fs in _group(res.findings).items():
        r = RULE_BY_ID[rid]
        worst = min((f.severity for f in fs), key=lambda x: SEVERITY_ORDER[x])
        out.append("%s %-7s %-6d %-6d %s%s" % (_c(SEV_LABEL[worst].ljust(7), SEV_COLOR[worst], color),
                                                 rid, len(fs), len({f.path for f in fs}), r.title,
                                                 "" if r.confidence == "documented" else "  [verify]"))
    if brief:
        return "\n".join(out) + "\n"
    for rid, fs in _group(res.findings).items():
        r = RULE_BY_ID[rid]
        worst = min((f.severity for f in fs), key=lambda x: SEVERITY_ORDER[x])
        out.append("")
        out.append(_c("%s  %s  (%d finding%s)  [%s]" % (rid, r.title, len(fs), "" if len(fs) == 1 else "s", CONF_TEXT[r.confidence]),
                      SEV_COLOR[worst] + ";1", color))
        for f in fs[:max_per_rule]:
            out.append("  %s:%d  %s%s" % (f.path, f.line, ", ".join(f.symbols[:4]), "   (inside Linux-only #if)" if f.guarded else ""))
        if len(fs) > max_per_rule:
            out.append("  ... and %d more (see the Markdown/JSON/SARIF report)" % (len(fs) - max_per_rule))
        out.append(textwrap.fill("QNX 8.0: " + r.qnx, width=100, initial_indent="  ", subsequent_indent="    "))
        for _t, url in r.docs[:3]:
            out.append("  docs: " + url)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
def render_markdown(res: ScanResult, name: str = "", max_per_rule: int = 15) -> str:
    name = project_name(res, name)
    s = summarize(res)
    sv = s["by_severity"]
    L: List[str] = []
    L.append("# QNX 8.0 porting report: %s" % name)
    L.append("")
    L.append("Generated by qnxport %s (docs cross-checked against the public QNX 8.0 documentation on %s)." % (__version__, DOCS_CHECKED))
    L.append("")
    L.append("| Scope | |")
    L.append("|---|---|")
    L.append("| Source files scanned | %d |" % len(res.source_files))
    L.append("| Lines of source | %s |" % format(res.loc, ","))
    L.append("| Build files scanned | %d |" % len(res.build_files))
    L.append("| Files already mentioning `__QNX__`/`__QNXNTO__` | %d |" % len(res.qnx_aware_files))
    L.append("| Rules triggered | %d |" % s["rules_triggered"])
    L.append("")
    L.append("| Severity | Findings |")
    L.append("|---|---|")
    for k, label in (("high", "High (no direct equivalent / build or link failure likely)"),
                     ("medium", "Medium (behaviour or flags differ)"),
                     ("low", "Low (usually only a build flag)"),
                     ("info", "Info (already inside a Linux-only `#if` branch, or project-level advice)")):
        L.append("| %s | %d |" % (label, sv[k]))
    L.append("")
    if not res.findings:
        L.append("No Linux-specific constructs from the rule set were found.")
        L.append("")
    else:
        L.append("## Where to start")
        L.append("")
        L.append("| Rule | Severity | Findings | Files | Confidence |")
        L.append("|---|---|---|---|---|")
        for rid, fs in _group(res.findings).items():
            r = RULE_BY_ID[rid]
            worst = min((f.severity for f in fs), key=lambda x: SEVERITY_ORDER[x])
            L.append("| [%s](#%s) %s | %s | %d | %d | %s |" % (rid, rid.lower(), r.title, worst, len(fs), len({f.path for f in fs}), CONF_TEXT[r.confidence]))
        L.append("")
        if s["top_files"]:
            L.append("Files with the most high/medium findings: " + ", ".join(
                "`%s` (%d)" % (t["file"], t["high_medium_findings"]) for t in s["top_files"][:5]) + ".")
            L.append("")
        for rid, fs in _group(res.findings).items():
            r = RULE_BY_ID[rid]
            L.append("## %s" % rid)
            L.append("")
            L.append("**%s** (category `%s`, base severity `%s`, %s)" % (r.title, r.category, r.severity, CONF_TEXT[r.confidence]))
            L.append("")
            L.append("- **Why it matters:** " + r.why)
            L.append("- **QNX 8.0 strategy:** " + r.qnx)
            if r.docs:
                L.append("- **QNX 8.0 docs:** " + "; ".join("[%s](%s)" % (t, u) for t, u in r.docs))
            L.append("")
            L.append("Locations (%d):" % len(fs))
            L.append("")
            for f in fs[:max_per_rule]:
                tag = " _(inside Linux-only `#if`)_" if f.guarded else ""
                L.append("- `%s:%d` `%s`%s" % (f.path, f.line, ", ".join(f.symbols[:4]).replace("`", "'"), tag))
                L.append("  `%s`" % f.snippet.replace("`", "'"))
                for t in f.notes:
                    L.append("  - note: " + t)
            if len(fs) > max_per_rule:
                L.append("- ... and %d more (full list in the JSON and SARIF reports)." % (len(fs) - max_per_rule))
            L.append("")
        verify = sorted({rid for rid in s["rules"] if RULE_BY_ID[rid].confidence == "verify"})
        L.append("## To verify on a QNX 8.0 SDP")
        L.append("")
        if verify:
            L.append("These triggered rules name a likely strategy that could not be confirmed from the public documentation: "
                     + ", ".join(verify) + ". Check each against your installed headers and the QNX documentation before relying on it.")
        else:
            L.append("All triggered rules are backed by a QNX 8.0 documentation page, but still compile and test on a target.")
        L.append("")
    L.append("## Method and limitations")
    L.append("")
    L.append(LIMITATIONS)
    L.append("")
    L.append("_Built by Nyx Agents Lab, a team of AI agents (Claude)._")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------
def render_json(res: ScanResult, name: str = "") -> str:
    name = project_name(res, name)
    s = summarize(res)
    used = {rid: RULE_BY_ID[rid] for rid in s["rules"]}
    doc = OrderedDict()
    doc["tool"] = {"name": "qnxport", "version": __version__, "target": "QNX 8.0", "qnx_docs_checked": DOCS_CHECKED}
    doc["scan"] = {"name": name, "source_files": len(res.source_files), "build_files": len(res.build_files), "lines": res.loc,
                   "qnx_aware_files": res.qnx_aware_files, "suppressed_findings": res.suppressed}
    doc["summary"] = s
    doc["rules"] = {rid: {"title": r.title, "category": r.category, "base_severity": r.severity, "confidence": r.confidence,
                          "why": r.why, "qnx_8_0": r.qnx, "docs": [{"title": t, "url": u} for t, u in r.docs]}
                    for rid, r in used.items()}
    doc["findings"] = [f.to_dict() for f in res.findings]
    doc["limitations"] = LIMITATIONS
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
