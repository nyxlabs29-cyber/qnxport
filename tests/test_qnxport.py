import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from qnxport import cli, generators, report, sarif  # noqa: E402
from qnxport.rules import ADVICE, RULES, RULE_BY_ID  # noqa: E402
from qnxport.scanner import blank_c, preprocessor_guard_map, scan_path, scan_source_text  # noqa: E402

FIX = os.path.join(HERE, "fixtures")


def ids_for(path, **kw):
    return {f.rule_id for f in scan_path(path, **kw).findings}


class LexerTests(unittest.TestCase):
    def test_comments_and_strings_blanked_keep_lines(self):
        src = 'int a; /* epoll_wait\nsendfile */ int b; // eventfd\nconst char *s = "getrandom \\" x";\n'
        nc, code, strings = blank_c(src)
        self.assertEqual(src.count("\n"), code.count("\n"))
        self.assertEqual(len(src), len(code))
        self.assertNotIn("epoll_wait", code)
        self.assertNotIn("eventfd", nc)
        self.assertIn("getrandom", nc)       # strings kept in the no-comment view
        self.assertNotIn("getrandom", code)  # but blanked in the code view
        self.assertEqual([(a, b) for a, b, _c in strings], [(3, 'getrandom \\" x')])

    def test_line_continuation_in_line_comment(self):
        src = "// comment \\\nepoll_wait();\nint x;\n"
        _, code, _ = blank_c(src)
        self.assertNotIn("epoll_wait", code)

    def test_char_literal_with_quote(self):
        src = "char c = '\"'; int epoll_wait_ok;\n"
        _, code, strings = blank_c(src)
        self.assertEqual(strings, [])
        self.assertIn("epoll_wait_ok", code)

    def test_raw_string(self):
        src = 'auto s = R"x(epoll_wait "quoted" )x"; int y;\n'
        _, code, strings = blank_c(src)
        self.assertNotIn("epoll_wait", code)
        self.assertEqual(len(strings), 1)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.res = scan_path(os.path.join(FIX, "linuxy"))
        self.by = {}
        for f in self.res.findings:
            self.by.setdefault((f.path, f.rule_id), []).append(f)

    def has(self, path, rid, line=None, sym=None):
        fs = self.by.get((path, rid), [])
        self.assertTrue(fs, "expected %s in %s" % (rid, path))
        if line is not None:
            self.assertIn(line, [f.line for f in fs])
        if sym is not None:
            self.assertTrue(any(sym in " ".join(f.symbols) for f in fs), "%s not in %s" % (sym, fs))

    def test_epoll_family(self):
        p = "epoll_loop.c"
        self.has(p, "QNX001", 4, "sys/epoll.h")
        self.has(p, "QNX001", 14, "epoll_create1")
        self.has(p, "QNX001", 20, "EPOLL_CTL_ADD")
        self.has(p, "QNX002", 16, "eventfd")
        self.has(p, "QNX003", 5, "timerfd")
        self.has(p, "QNX004", 7, "signalfd")

    def test_epoll_notes(self):
        f = [x for x in self.by[("epoll_loop.c", "QNX001")] if x.line == 19][0]
        self.assertTrue(any("EDGEARM" in n for n in f.notes))

    def test_comments_and_strings_not_reported(self):
        lines = {f.line for f in self.by[("epoll_loop.c", "QNX001")]}
        self.assertNotIn(9, lines)    # comment line
        self.assertNotIn(10, lines)   # string literal
        self.assertNotIn(("epoll_loop.c", "QNX010"), self.by)

    def test_proc_strings(self):
        self.has("epoll_loop.c", "QNX013", 30, "/proc/cpuinfo")
        fs = self.by[("epoll_loop.c", "QNX013")]
        self.assertTrue(any("exefile" in n for f in fs for n in f.notes))

    def test_misc_apis(self):
        p = "misc.c"
        for rid, sym in (("QNX007", "prctl"), ("QNX008", "sched_setaffinity"), ("QNX009", "sendfile"),
                         ("QNX010", "getrandom"), ("QNX011", "memfd_create"), ("QNX012", "sysinfo"),
                         ("QNX022", "syscall"), ("QNX023", "accept4"), ("QNX024", "fallocate"), ("QNX025", "statfs"),
                         ("QNX026", "CLOCK_BOOTTIME"), ("QNX027", "MAP_POPULATE"), ("QNX021", "pthread_yield"),
                         ("QNX005", "inotify_init1"), ("QNX014", "/sys/class/gpio"), ("QNX015", "/dev/shm"),
                         ("QNX016", "/dev/mem"), ("QNX017", "linux/input.h")):
            self.has(p, rid, None, sym)

    def test_syscall_gettid_note(self):
        fs = self.by[("misc.c", "QNX022")]
        self.assertTrue(any("gettid" in n for f in fs for n in f.notes))

    def test_advice_rules(self):
        ids = {f.rule_id for f in self.res.findings}
        self.assertIn("QNX150", ids)   # sockets, no -lsocket in the fixture build files
        self.assertIn("QNX151", ids)   # inotify, no -lfsnotify

    def test_build_rules(self):
        self.has("Makefile", "QNX101", 5, "-lrt")
        self.has("Makefile", "QNX102", 2)
        self.has("Makefile", "QNX103", 1)
        self.has("Makefile", "QNX104", 3)
        self.has("CMakeLists.txt", "QNX104", 3)
        self.has("CMakeLists.txt", "QNX101", 7)
        lines = {f.line for f in self.by[("CMakeLists.txt", "QNX101")]}
        self.assertNotIn(8, lines)    # commented out

    def test_guards(self):
        fs = [f for f in self.res.findings if f.path == "guards.c" and f.rule_id in ("QNX001", "QNX002")]
        by_line = {(f.rule_id, f.line): f for f in fs}
        self.assertTrue(by_line[("QNX001", 3)].guarded)   # include inside #ifdef __linux__
        self.assertTrue(by_line[("QNX001", 4)].guarded)
        self.assertEqual(by_line[("QNX001", 4)].severity, "info")
        self.assertEqual(by_line[("QNX001", 4)].base_severity, "high")
        self.assertTrue(by_line[("QNX002", 13)].guarded)   # #ifndef __linux__ ... #else
        self.assertFalse(by_line[("QNX002", 17)].guarded)  # mixed linux||qnx: not treated as guarded
        self.assertEqual(by_line[("QNX002", 17)].severity, "high")

    def test_preprocessor_guard_map(self):
        lines = ["#if defined(__linux__)", "a", "#elif defined(__QNXNTO__)", "b", "#endif", "c"]
        self.assertEqual(preprocessor_guard_map(lines), [False, True, True, False, False, False])

    def test_suppression(self):
        r = scan_path(os.path.join(FIX, "linuxy", "suppress.c"))
        self.assertEqual([f.rule_id for f in r.findings if f.rule_id in ("QNX001", "QNX002")], [])
        self.assertGreaterEqual(r.suppressed, 3)

    def test_ignore_file_directive(self):
        text = "// qnxport:ignore-file\n#include <sys/epoll.h>\n"
        self.assertEqual(scan_source_text(text, "x.c"), [])
        text = "// qnxport:ignore-file QNX001\n#include <sys/epoll.h>\n#include <sys/eventfd.h>\n"
        self.assertEqual([f.rule_id for f in scan_source_text(text, "x.c")], ["QNX002"])

    def test_clean_file_has_no_findings(self):
        r = scan_path(os.path.join(FIX, "clean"))
        self.assertEqual(r.findings, [])
        self.assertEqual(r.qnx_aware_files, ["portable.c"])

    def test_exclude_and_ignore(self):
        self.assertNotIn("epoll_loop.c", {f.path for f in scan_path(os.path.join(FIX, "linuxy"), exclude=["epoll_*"]).findings})
        self.assertNotIn("QNX001", ids_for(os.path.join(FIX, "linuxy"), ignore_rules=["QNX001"]))


class RuleDatabaseTests(unittest.TestCase):
    def test_unique_ids_and_patterns(self):
        ids = [r.id for r in RULES]
        self.assertEqual(len(ids), len(set(ids)))
        for r in RULES:
            self.assertTrue(r.inc or r.sym or r.string or r.build, r.id)
            self.assertIn(r.confidence, ("documented", "verify"))
            self.assertIn(r.severity, ("high", "medium", "low", "info"))
            self.assertTrue(r.qnx and r.why and r.title)
            for rx in r.inc + r.sym + r.string + r.build + [n[0] for n in r.notes]:
                re.compile(rx)

    def test_docs_links_point_to_qnx_80_docs(self):
        for r in list(RULES) + list(ADVICE.values()):
            for _t, url in r.docs:
                self.assertTrue(url.startswith("https://www.qnx.com/developers/docs/8.0/"), (r.id, url))
                self.assertTrue(url.endswith(".html"))

    def test_documented_rules_have_docs(self):
        for r in RULES:
            if r.confidence == "documented":
                self.assertTrue(r.docs, r.id)

    def test_every_rule_fires_on_a_probe(self):
        probes = {
            "QNX001": "#include <sys/epoll.h>", "QNX002": "int x = eventfd(0,0);", "QNX003": "timerfd_create(1,0);",
            "QNX004": "signalfd(-1,&m,0);", "QNX005": "inotify_init();", "QNX006": "fanotify_init(0,0);",
            "QNX007": "prctl(1,2);", "QNX008": "sched_setaffinity(0,1,&s);", "QNX009": "splice(a,0,b,0,1,0);",
            "QNX010": "getentropy(b,1);", "QNX011": "memfd_create(\"a\",0);", "QNX012": "get_nprocs();",
            "QNX013": 'f("/proc/meminfo");', "QNX014": 'f("/sys/class/net");', "QNX015": 'f("/dev/shm/a");',
            "QNX016": 'f("/dev/mem");', "QNX017": "#include <linux/i2c-dev.h>", "QNX018": "ioctl(fd, BLKGETSIZE64, &s);",
            "QNX019": "#ifdef __linux__", "QNX020": "strchrnul(s, 'a');", "QNX021": "pthread_yield();",
            "QNX022": "#include <sys/syscall.h>", "QNX023": "dup3(a,b,0);", "QNX024": "sync_file_range(f,0,0,0);",
            "QNX025": "statfs(p,&s);", "QNX026": "t = CLOCK_MONOTONIC_RAW;", "QNX027": "x = mremap(a,1,2,0);",
            "QNX028": "open(p, O_TMPFILE);", "QNX029": "#include <sys/capability.h>", "QNX030": "unshare(0);",
            "QNX031": "ptrace(0,0,0,0);", "QNX032": "p = SCHED_IDLE;", "QNX033": "e.sigev_notify = SIGEV_THREAD_ID;",
            "QNX034": "setsockopt(s, 6, TCP_CORK, &o, 4);", "QNX035": "#include <systemd/sd-daemon.h>",
            "QNX036": "#include <alsa/asoundlib.h>", "QNX037": "getsockopt(s, 1, SO_PEERCRED, &c, &l);",
        }
        for r in RULES:
            if r.kind == "build":
                continue
            self.assertIn(r.id, probes, "add a probe for %s" % r.id)
            got = {f.rule_id for f in scan_source_text("void f(void){\n%s\n}\n" % probes[r.id], "p.c")}
            self.assertIn(r.id, got, r.id)

    def test_build_rules_fire(self):
        build_probes = {"QNX101": "LDLIBS = -lrt", "QNX102": "CFLAGS += -march=native", "QNX103": "CC = gcc",
                        "QNX104": "OS := $(shell uname -s)", "QNX105": "CFLAGS += -fsanitize=address"}
        for rid, line in build_probes.items():
            from qnxport.scanner import scan_build_text
            self.assertEqual([f.rule_id for f in scan_build_text(line + "\n", "Makefile")], [rid])


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.res = scan_path(os.path.join(FIX, "linuxy"))

    def test_json(self):
        d = json.loads(report.render_json(self.res, "fixture"))
        self.assertEqual(d["tool"]["name"], "qnxport")
        self.assertEqual(d["scan"]["name"], "fixture")
        self.assertEqual(d["summary"]["total"], len(d["findings"]))
        for f in d["findings"]:
            self.assertIn(f["rule"], d["rules"])
            self.assertGreater(f["line"], 0)
        self.assertIn("docs", d["rules"]["QNX001"])

    def test_sarif_structure(self):
        d = json.loads(sarif.render_sarif(self.res))
        self.assertEqual(d["version"], "2.1.0")
        run = d["runs"][0]
        rules = run["tool"]["driver"]["rules"]
        self.assertEqual(len({r["id"] for r in rules}), len(rules))
        self.assertTrue(run["results"])
        for res in run["results"]:
            self.assertEqual(rules[res["ruleIndex"]]["id"], res["ruleId"])
            self.assertIn(res["level"], ("error", "warning", "note"))
            loc = res["locations"][0]["physicalLocation"]
            self.assertGreaterEqual(loc["region"]["startLine"], 1)
            self.assertFalse(loc["artifactLocation"]["uri"].startswith("/"))
            self.assertIn("qnxportFinding/v1", res["partialFingerprints"])
        levels = {r["level"] for r in run["results"]}
        self.assertEqual(levels, {"error", "warning", "note"})

    def test_markdown(self):
        md = report.render_markdown(self.res, "fixture")
        self.assertIn("# QNX 8.0 porting report: fixture", md)
        self.assertIn("## QNX001", md)
        self.assertIn("https://www.qnx.com/developers/docs/8.0/", md)
        self.assertIn("Built by Nyx Agents Lab, a team of AI agents (Claude)", md)

    def test_text(self):
        t = report.render_text(self.res, "fixture")
        self.assertIn("QNX001", t)
        self.assertIn("epoll_loop.c:4", t)
        t2 = report.render_text(scan_path(os.path.join(FIX, "clean")), "clean")
        self.assertIn("No Linux-specific constructs", t2)


class GeneratorTests(unittest.TestCase):
    def test_makefile(self):
        res = scan_path(os.path.join(FIX, "linuxy"))
        mk = generators.makefile_fragment(res, "demo")
        self.assertIn("qcc -V$(QCC_TARGET)", mk)
        self.assertIn("gcc_nto$(QNX_ARCH)", mk)
        self.assertIn("-lfsnotify", mk)
        self.assertIn("-lsocket", mk)
        self.assertIn("STARTER FILE", mk)
        self.assertIn("NOT run", mk)
        self.assertIn("\t$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c -o $@ $<", mk)   # recipes use tabs
        self.assertNotIn("    $(CC)", mk)

    def test_cmake_toolchains(self):
        for arch in ("aarch64le", "x86_64"):
            t = generators.cmake_toolchain(arch)
            self.assertIn("set(QNX_ARCH %s)" % arch, t)
            self.assertIn("CMAKE_SYSTEM_NAME      QNX", t)
            self.assertIn("gcc_nto${QNX_ARCH}", t)
            self.assertEqual(t.count("{"), t.count("}"))
            self.assertEqual(t.count("("), t.count(")"))

    def test_ci_workflow_matches_example(self):
        ex = os.path.join(os.path.dirname(HERE), "examples", "github-action", "qnxport.yml")
        if os.path.exists(ex):
            with open(ex, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), generators.GITHUB_ACTION)
        self.assertIn("upload-sarif", generators.GITHUB_ACTION)
        self.assertIn("pull_request", generators.GITHUB_ACTION)

    def test_scaffold_writes_files(self):
        with tempfile.TemporaryDirectory() as td:
            res = scan_path(os.path.join(FIX, "linuxy"))
            written = generators.write_scaffold(res, td, "demo")
            names = sorted(os.path.basename(p) for p in written)
            self.assertEqual(names, ["Makefile.qnx", "qnx-toolchain-aarch64le.cmake", "qnx-toolchain-x86_64.cmake"])


class CliTests(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_scan_writes_reports_and_fail_on(self):
        with tempfile.TemporaryDirectory() as td:
            code, out, err = self.run_cli("scan", os.path.join(FIX, "linuxy"), "--out-dir", td, "--fail-on", "high")
            self.assertEqual(code, 1)
            self.assertIn("QNX001", out)
            for n in ("qnxport-report.md", "qnxport-report.json", "qnxport-report.sarif"):
                self.assertTrue(os.path.exists(os.path.join(td, n)), n)
            with open(os.path.join(td, "qnxport-report.sarif"), encoding="utf-8") as fh:
                json.load(fh)

    def test_clean_passes_fail_on(self):
        code, out, _ = self.run_cli(os.path.join(FIX, "clean"), "--fail-on", "info")   # shorthand without 'scan'
        self.assertEqual(code, 0)

    def test_bad_args(self):
        self.assertEqual(self.run_cli("scan", os.path.join(FIX, "nope"))[0], 2)
        self.assertEqual(self.run_cli("scan", FIX, "--ignore", "QNX999")[0], 2)
        self.assertEqual(self.run_cli("explain", "QNX999")[0], 2)

    def test_explain_and_rules(self):
        code, out, _ = self.run_cli("explain", "qnx001")
        self.assertEqual(code, 0)
        self.assertIn("ionotify", out)
        code, out, _ = self.run_cli("rules", "--format", "markdown")
        self.assertIn("| QNX001 |", out)

    def test_scaffold_command(self):
        with tempfile.TemporaryDirectory() as td:
            code, out, _ = self.run_cli("scaffold", os.path.join(FIX, "linuxy"), "--out", td, "--arch", "x86_64")
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(td, "qnx-toolchain-x86_64.cmake")))
            self.assertFalse(os.path.exists(os.path.join(td, "qnx-toolchain-aarch64le.cmake")))


if __name__ == "__main__":
    unittest.main()


class QuotedIncludeTests(unittest.TestCase):
    def test_quoted_linux_dir_is_project_header(self):
        self.assertEqual(scan_source_text('#include "linux/Platform.h"\n', "a.c"), [])
        self.assertEqual([f.rule_id for f in scan_source_text("#include <linux/input.h>\n", "a.c")], ["QNX017"])


class MacroPathTests(unittest.TestCase):
    def test_macro_prefixed_literal_is_not_a_sysfs_path(self):
        src = 'void f(void){ fopen(PROCDIR "/sys/kernel/pid_max", "r"); fopen("/sys/kernel/x", "r"); }\n'
        got = scan_source_text(src, "a.c")
        self.assertEqual([f.rule_id for f in got], ["QNX014"])
        self.assertIn('"/sys/kernel/x"', got[0].symbols[0])

    def test_columns_after_multiline_comment(self):
        src = '/* a\nb */ open("/proc/cpuinfo", 0);\n'
        self.assertEqual([f.rule_id for f in scan_source_text(src, "a.c")], ["QNX013"])


class AffinityNoteTests(unittest.TestCase):
    def test_affinity_rule_mentions_calling_thread_limit(self):
        self.assertIn("calling thread", RULE_BY_ID["QNX008"].qnx)
