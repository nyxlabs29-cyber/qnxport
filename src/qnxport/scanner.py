"""Static scanner: finds Linux-specific constructs in C/C++ sources and build files.

No compiler is invoked. The scanner is a small lexer (comments and string
literals are understood, so a function name inside a comment or a string does
not trigger a finding) plus a minimal preprocessor-conditional tracker (so
code that is already inside a Linux-only #if branch is reported as such).
"""

import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .rules import ADVICE, RULES, RULE_BY_ID, Rule, SEVERITY_ORDER

SOURCE_EXT = {".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx", ".inl", ".ipp", ".c++", ".h++"}
BUILD_NAMES = {"makefile", "gnumakefile", "cmakelists.txt", "configure.ac", "configure.in", "meson.build",
               "makefile.am", "meson_options.txt"}
BUILD_EXT = {".mk", ".cmake", ".make"}
DEFAULT_EXCLUDE_DIRS = {".git", ".hg", ".svn", "node_modules", "build", "dist", "__pycache__", ".venv", "CMakeFiles"}
MAX_FILE_BYTES = 8 * 1024 * 1024

LINUX_TOKENS = r"(?:__linux__|__linux|__gnu_linux__|linux|__GLIBC__|__GNU_LIBRARY__|__KERNEL__)"
QNX_TOKENS = r"(?:__QNX__|__QNXNTO__)"
IGNORE_RE = re.compile(r"qnxport:\s*ignore(?!-file)(?:[ \t]+([A-Z0-9_, \t]+))?")
IGNORE_FILE_RE = re.compile(r"qnxport:\s*ignore-file(?:[ \t]+([A-Z0-9_, \t]+))?")
# group 1: <system> include path, group 2: "quoted" include path
INCLUDE_RE = re.compile(r"^\s*#\s*(?:include|include_next|import)\s*(?:<([^>]+)>|\"([^\"]+)\")")


def system_include(line: str) -> Optional[str]:
    """Path of a <...> include on this line, else None. Quoted includes name project headers and are never matched
    against the Linux-header rules (a project may have its own linux/ directory)."""
    m = INCLUDE_RE.match(line)
    return m.group(1).strip() if m and m.group(1) else None


@dataclass
class Finding:
    rule_id: str
    path: str
    line: int
    severity: str
    base_severity: str
    symbols: List[str]
    snippet: str
    notes: List[str] = field(default_factory=list)
    guarded: bool = False       # already inside a Linux-only #if branch

    def to_dict(self) -> dict:
        return {"rule": self.rule_id, "file": self.path, "line": self.line, "severity": self.severity,
                "base_severity": self.base_severity, "symbols": self.symbols, "snippet": self.snippet,
                "notes": self.notes, "linux_guarded": self.guarded}


@dataclass
class ScanResult:
    root: str
    findings: List[Finding] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    build_files: List[str] = field(default_factory=list)
    loc: int = 0
    qnx_aware_files: List[str] = field(default_factory=list)
    suppressed: int = 0


# --------------------------------------------------------------------------
# Lexer
# --------------------------------------------------------------------------
def blank_c(text: str) -> Tuple[str, str, List[Tuple[int, str, int]]]:
    """Return (nocomment, code, strings).

    nocomment: comments replaced by spaces, strings kept.
    code:      comments replaced by spaces, string/char literal contents replaced by spaces.
    strings:   [(line_number, content, column_of_opening_quote)] for every string literal.
    Newlines are preserved so line numbers stay valid.
    """
    n = len(text)
    nc = list(text)
    cd = list(text)
    strings: List[Tuple[int, str, int]] = []
    i = 0
    line = 1

    def blank(lst, a, b):
        for k in range(a, b):
            if lst[k] != "\n":
                lst[k] = " "

    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            j = i
            while j < n:
                if text[j] == "\n":
                    if j > 0 and text[j - 1] == "\\":
                        line += 1
                        j += 1
                        continue
                    break
                j += 1
            blank(nc, i, j)
            blank(cd, i, j)
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += text.count("\n", i, j)
            blank(nc, i, j)
            blank(cd, i, j)
            i = j
        elif c == '"' or c == "'":
            # raw string literal R"delim( ... )delim"
            if c == '"' and i > 0 and text[i - 1] == "R" and (i < 2 or not (text[i - 2].isalnum() or text[i - 2] == "_")):
                m = re.compile(r'"([^()\\ ]{0,16})\(').match(text, i)
                if m:
                    end = ")" + m.group(1) + '"'
                    j = text.find(end, m.end())
                    j = n if j < 0 else j + len(end)
                    strings.append((line, text[m.end():max(m.end(), j - len(end))], i - (text.rfind("\n", 0, i) + 1)))
                    line += text.count("\n", i, j)
                    blank(cd, i + 1, j - 1)
                    i = j
                    continue
            j = i + 1
            start_line = line
            while j < n and text[j] != c:
                if text[j] == "\\" and j + 1 < n:
                    if text[j + 1] == "\n":
                        line += 1
                    j += 2
                    continue
                if text[j] == "\n":      # unterminated: stop at end of line
                    break
                j += 1
            if c == '"':
                strings.append((start_line, text[i + 1:j], i - (text.rfind("\n", 0, i) + 1)))
            blank(cd, i + 1, j)
            i = j + 1 if j < n and text[j] == c else j
        else:
            i += 1
    return "".join(nc), "".join(cd), strings


# --------------------------------------------------------------------------
# Preprocessor tracking
# --------------------------------------------------------------------------
def _linux_positive(expr: str) -> bool:
    """True if expr is a plain 'Linux-only' condition (no QNX token, no ||, not negated)."""
    if re.search(QNX_TOKENS, expr) or "||" in expr:
        return False
    for m in re.finditer(r"(!?\s*(?:defined\s*\(?\s*)?)(" + LINUX_TOKENS + r")\b", expr):
        if "!" not in m.group(1):
            return True
    return False


def _linux_negated(expr: str) -> bool:
    if re.search(QNX_TOKENS, expr):
        return False
    return bool(re.search(r"!\s*(?:defined\s*\(?\s*)?" + LINUX_TOKENS + r"\b", expr))


def preprocessor_guard_map(code_lines: List[str]) -> List[bool]:
    """For each line: True if inside a Linux-only #if branch."""
    result = [False] * len(code_lines)
    stack: List[dict] = []
    i = 0
    while i < len(code_lines):
        raw = code_lines[i]
        result[i] = any(e["guard"] for e in stack)
        m = re.match(r"^\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)$", raw)
        if not m:
            i += 1
            continue
        kind, rest = m.group(1), m.group(2)
        j = i
        while rest.rstrip().endswith("\\") and j + 1 < len(code_lines):    # continued directive
            j += 1
            rest = rest.rstrip()[:-1] + " " + code_lines[j]
            result[j] = result[i]
        if kind in ("ifdef", "ifndef"):
            expr = ("defined(%s)" if kind == "ifdef" else "!defined(%s)") % rest.strip().split()[0] if rest.strip() else ""
            stack.append({"guard": _linux_positive(expr), "neg": _linux_negated(expr)})
        elif kind == "if":
            stack.append({"guard": _linux_positive(rest), "neg": _linux_negated(rest)})
        elif kind == "elif" and stack:
            stack[-1]["guard"] = _linux_positive(rest)
            stack[-1]["neg"] = _linux_negated(rest)
        elif kind == "else" and stack:
            stack[-1]["guard"] = stack[-1]["neg"] and not stack[-1]["guard"]
        elif kind == "endif" and stack:
            stack.pop()
        i = j + 1
    return result


# --------------------------------------------------------------------------
# Compiled rules
# --------------------------------------------------------------------------
def _alt(patterns: List[str]) -> Optional["re.Pattern"]:
    if not patterns:
        return None
    return re.compile("|".join("(?:%s)" % p for p in patterns))


class _Compiled:
    def __init__(self, rule: Rule):
        self.rule = rule
        self.inc = _alt(rule.inc)
        self.sym = _alt(rule.sym)
        self.string = _alt(rule.string)
        self.build = _alt(rule.build)
        self.notes = [(re.compile(rx), text) for rx, text in rule.notes]


_COMPILED = [_Compiled(r) for r in RULES]
_SRC = [c for c in _COMPILED if c.rule.kind == "source"]
_BLD = [c for c in _COMPILED if c.rule.kind == "build"]


def _clean_symbol(s: str) -> str:
    return re.sub(r"\s*\($", "", re.sub(r"\s+", " ", s.strip()))


def _effective_severity(base: str, guarded: bool) -> str:
    return "info" if guarded else base


def _snippet(line: str) -> str:
    s = line.strip()
    return s if len(s) <= 160 else s[:157] + "..."


def _ignored(rule_id: str, raw_lines: List[str], idx: int) -> bool:
    for k in (idx, idx - 1):
        if 0 <= k < len(raw_lines):
            m = IGNORE_RE.search(raw_lines[k])
            if m:
                ids = (m.group(1) or "").replace(",", " ").split()
                if not ids or rule_id in ids:
                    return True
    return False


def scan_source_text(text: str, relpath: str, ignore_rules=frozenset(), result: Optional[ScanResult] = None) -> List[Finding]:
    mfile = IGNORE_FILE_RE.search(text)
    file_ignored = set()
    if mfile:
        ids = (mfile.group(1) or "").replace(",", " ").split()
        file_ignored = set(ids) if ids else {"*"}
    if "*" in file_ignored:
        return []
    nocomment, code, strings = blank_c(text)
    raw_lines = text.split("\n")
    nc_lines = nocomment.split("\n")
    code_lines = code.split("\n")
    guards = preprocessor_guard_map(code_lines)
    strings_by_line: Dict[int, List[str]] = {}
    for ln, content, col in strings:
        # A literal glued to a preceding macro/identifier (PROCDIR "/sys/kernel/x") is only the tail of a path.
        before = code_lines[ln - 1][:col] if 0 < ln <= len(code_lines) else ""
        if content.startswith("/") and re.search(r"[A-Za-z_][A-Za-z0-9_]*\s*$", before):
            continue
        strings_by_line.setdefault(ln, []).append(content)

    found: Dict[Tuple[str, int], Finding] = {}
    suppressed = 0

    def add(c: _Compiled, lineno: int, symbols: List[str], ctx: str):
        nonlocal suppressed
        rid = c.rule.id
        if rid in ignore_rules or rid in file_ignored:
            return
        if _ignored(rid, raw_lines, lineno - 1):
            suppressed += 1
            return
        key = (rid, lineno)
        notes = [t for rx, t in c.notes if rx.search(ctx)]
        guarded = guards[lineno - 1]
        if key in found:
            f = found[key]
            for s in symbols:
                if s not in f.symbols:
                    f.symbols.append(s)
            for t in notes:
                if t not in f.notes:
                    f.notes.append(t)
            return
        found[key] = Finding(rid, relpath, lineno, _effective_severity(c.rule.severity, guarded), c.rule.severity,
                             list(dict.fromkeys(symbols)), _snippet(raw_lines[lineno - 1]), list(dict.fromkeys(notes)), guarded)

    for idx, cl in enumerate(code_lines):
        lineno = idx + 1
        is_inc_line = ("include" in nc_lines[idx] or "import" in nc_lines[idx]) and INCLUDE_RE.match(nc_lines[idx]) is not None
        inc_path = system_include(nc_lines[idx]) if is_inc_line else None
        for c in _SRC:
            if c.inc is not None and inc_path:
                m = c.inc.search(inc_path)
                if m:
                    add(c, lineno, ["#include <%s>" % inc_path], inc_path)
            if c.sym is not None and cl.strip() and not is_inc_line:
                hits = [m.group(0) for m in c.sym.finditer(cl)]
                if hits:
                    clean = [_clean_symbol(h) for h in hits]
                    add(c, lineno, clean, " ".join(clean))
            if c.string is not None and lineno in strings_by_line:
                for s in strings_by_line[lineno]:
                    m = c.string.search(s)
                    if m:
                        add(c, lineno, ['"%s"' % (s if len(s) <= 60 else s[:57] + "...")], s)
    if result is not None:
        result.suppressed += suppressed
    return sorted(found.values(), key=lambda f: (f.line, f.rule_id))


def _strip_build_comment(name: str, line: str) -> str:
    low = name.lower()
    if low.endswith("configure.ac") or low.endswith("configure.in"):
        if re.match(r"^\s*dnl\b", line):
            return ""
    # '#' starts a comment in Make/CMake/Meson/m4 (good enough: we do not try to honour quoted '#')
    return line.split("#", 1)[0] if "#" in line else line


def scan_build_text(text: str, relpath: str, ignore_rules=frozenset()) -> List[Finding]:
    raw_lines = text.split("\n")
    out: Dict[Tuple[str, int], Finding] = {}
    for idx, raw in enumerate(raw_lines):
        line = _strip_build_comment(relpath, raw)
        if not line.strip():
            continue
        for c in _BLD:
            if c.rule.id in ignore_rules:
                continue
            hits = [m.group(0).strip(" \t'\"=") for m in c.build.finditer(line)]
            if not hits or _ignored(c.rule.id, raw_lines, idx):
                continue
            out[(c.rule.id, idx + 1)] = Finding(c.rule.id, relpath, idx + 1, c.rule.severity, c.rule.severity,
                                                 list(dict.fromkeys(hits)), _snippet(raw), [], False)
    return sorted(out.values(), key=lambda f: (f.line, f.rule_id))


# --------------------------------------------------------------------------
# Tree walk
# --------------------------------------------------------------------------
def classify(name: str) -> Optional[str]:
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if ext in SOURCE_EXT:
        return "source"
    if low in BUILD_NAMES or ext in BUILD_EXT:
        return "build"
    return None


def iter_files(root: str, exclude: List[str]):
    root = os.path.abspath(root)
    if os.path.isfile(root):
        k = classify(os.path.basename(root))
        if k:
            yield os.path.dirname(root), os.path.basename(root), k
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS)
        for fn in sorted(filenames):
            k = classify(fn)
            if not k:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(fn, pat) for pat in exclude):
                continue
            yield root, rel, k


def read_text(path: str) -> Optional[str]:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def scan_path(path: str, exclude: Optional[List[str]] = None, ignore_rules=()) -> ScanResult:
    exclude = list(exclude or [])
    ignore = frozenset(ignore_rules)
    res = ScanResult(root=os.path.abspath(path))
    build_texts: List[str] = []
    socket_site: Optional[Tuple[str, int]] = None
    inotify_site: Optional[Tuple[str, int]] = None
    for base, rel, kind in iter_files(path, exclude):
        full = os.path.join(base, rel) if os.path.isdir(res.root) else res.root
        text = read_text(full)
        if text is None:
            continue
        if os.path.isfile(res.root):
            rel = os.path.basename(res.root)
        if kind == "source":
            res.source_files.append(rel)
            res.loc += text.count("\n") + 1
            if re.search(r"\b__QNX(?:NTO)?__\b", text):
                res.qnx_aware_files.append(rel)
            fs = scan_source_text(text, rel, ignore, res)
            res.findings.extend(fs)
            for ln, line in enumerate(text.split("\n"), 1):
                inc = system_include(line)
                if not inc:
                    continue
                if socket_site is None and inc in ("sys/socket.h", "netinet/in.h", "arpa/inet.h", "netdb.h"):
                    socket_site = (rel, ln)
                if inotify_site is None and inc == "sys/inotify.h":
                    inotify_site = (rel, ln)
        else:
            res.build_files.append(rel)
            build_texts.append(text)
            res.findings.extend(scan_build_text(text, rel, ignore))
    joined = "\n".join(build_texts)
    if socket_site and "QNX150" not in ignore and not re.search(r"(?:-l\s*socket\b|\bsocket\b\s*[)\s])", joined):
        rel, ln = socket_site
        a = ADVICE["QNX150"]
        res.findings.append(Finding(a.id, rel, ln, a.severity, a.severity, ["#include <sys/socket.h>-family"],
                                    "sockets used; no -lsocket found in %d build file(s)" % len(res.build_files)))
    if inotify_site and "QNX151" not in ignore and "fsnotify" not in joined:
        rel, ln = inotify_site
        a = ADVICE["QNX151"]
        res.findings.append(Finding(a.id, rel, ln, a.severity, a.severity, ["#include <sys/inotify.h>"],
                                    "inotify used; no -lfsnotify found in %d build file(s)" % len(res.build_files)))
    res.findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.path, f.line, f.rule_id))
    return res
