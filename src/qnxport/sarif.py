"""SARIF 2.1.0 output (GitHub code scanning compatible)."""

import hashlib
import json
from typing import List

from . import __version__
from .rules import RULE_BY_ID, RULES, SARIF_LEVEL, ADVICE
from .scanner import ScanResult

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFO_URI = "https://github.com/nyxlabs29-cyber/qnxport"


def _rule_entry(r) -> dict:
    help_md = "**QNX 8.0 strategy:** %s\n\n**Why:** %s\n\n%s" % (
        r.qnx, r.why, "\n".join("- [%s](%s)" % (t, u) for t, u in r.docs))
    return {
        "id": r.id,
        "name": r.title.title().replace(" ", "").replace("/", "").replace("(", "").replace(")", "").replace("-", ""),
        "shortDescription": {"text": r.title},
        "fullDescription": {"text": r.why},
        "help": {"text": "QNX 8.0 strategy: %s (confidence: %s)" % (r.qnx, r.confidence), "markdown": help_md},
        "helpUri": r.docs[0][1] if r.docs else INFO_URI,
        "defaultConfiguration": {"level": SARIF_LEVEL[r.severity]},
        "properties": {"tags": ["qnx", "qnx-8.0", "porting", r.category, "confidence-" + r.confidence],
                       "qnxport-confidence": r.confidence},
    }


def render_sarif(res: ScanResult) -> str:
    used = {f.rule_id for f in res.findings}
    all_rules = [r for r in list(RULES) + list(ADVICE.values()) if r.id in used]   # only rules that fired
    index = {r.id: i for i, r in enumerate(all_rules)}
    results: List[dict] = []
    for f in res.findings:
        r = RULE_BY_ID[f.rule_id]
        text = "%s: %s. QNX 8.0: %s [%s]" % (r.title, ", ".join(f.symbols[:4]), r.qnx,
                                              "documented" if r.confidence == "documented" else "verify on your SDP")
        if f.guarded:
            text += " (already inside a Linux-only #if branch; make sure a QNX branch exists)"
        for n in f.notes:
            text += " Note: " + n
        fp = hashlib.sha1(("%s|%s|%s" % (f.rule_id, f.path, f.snippet)).encode("utf-8")).hexdigest()
        results.append({
            "ruleId": f.rule_id,
            "ruleIndex": index[f.rule_id],
            "level": SARIF_LEVEL[f.severity],
            "message": {"text": text},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": f.path, "uriBaseId": "%SRCROOT%"},
                "region": {"startLine": f.line, "snippet": {"text": f.snippet}}}}],
            "partialFingerprints": {"qnxportFinding/v1": fp},
            "properties": {"severity": f.severity, "baseSeverity": f.base_severity, "linuxGuarded": f.guarded,
                           "confidence": r.confidence},
        })
    doc = {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "qnxport", "version": __version__, "semanticVersion": __version__,
                                "informationUri": INFO_URI, "rules": [_rule_entry(r) for r in all_rules]}},
            "originalUriBaseIds": {"%SRCROOT%": {"uri": "file:///"}},
            "results": results,
        }],
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
