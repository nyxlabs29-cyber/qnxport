# qnxport

**A host-side porting assistant for QNX OS 8.0.** Point it at a C/C++ Linux/POSIX project and it tells you, file and line, what will not
work on QNX 8.0, what to do instead (with a link to the QNX 8.0 documentation page the advice is based on), and it writes the starter build
files. It runs on your development host, needs only Python 3 (standard library, no dependencies) and never touches the target.

> Built by Nyx Agents Lab, a team of AI agents (Claude). Entry for the QNX Global Hackathon, category *Developer Tooling & Host Tools*.

```
pip install .
qnxport scan path/to/project --out-dir report/      # terminal summary + Markdown + JSON + SARIF
qnxport scaffold path/to/project                    # qcc Makefile fragment + CMake toolchain files
qnxport init-ci --out .github/workflows/qnxport.yml # GitHub Actions workflow (SARIF to code scanning)
```

## Why

Porting a Linux daemon to QNX usually starts with a long list of compile errors, then a second list of things that compile but
behave differently (`/proc` files that are not there, `epoll` loops, `sched_setaffinity()` on another thread, `-lrt -ldl -lpthread`
link lines, `#ifdef __linux__` branches that silently vanish). Engineers rediscover the same answers one build at a time.
qnxport front-loads that: a static scan in seconds, a prioritised report, and every recommendation traceable to documentation.

## What it detects

44 rules (42 pattern rules plus 2 project-level advice items; `qnxport rules`, full table in [docs/rules.md](docs/rules.md)) in four groups:

| Group | Examples |
|---|---|
| Event and fd primitives | `epoll_*`, `eventfd`, `timerfd_*`, `signalfd`, `inotify` (available on QNX 8.0 but needs `-lfsnotify` and `fsevmgr`), `fanotify` |
| Process, scheduling, security | `prctl`, `sched_setaffinity` / `pthread_setaffinity_np` / `CPU_SET`, `syscall(SYS_*)`, `pthread_yield`, capabilities, namespaces/seccomp/cgroups, `ptrace`, SCHED_* policies |
| I/O and system interfaces | `sendfile`/`splice`, `getrandom`, `memfd_create`, `sysinfo`, `statfs`, `/proc`, `/sys`, `/dev/shm`, `/dev/mem`, `<linux/*.h>`, Linux ioctls, `accept4`/`dup3`, Linux-only clock IDs, mmap and open flags, systemd/udev, ALSA, netlink and Linux socket options |
| Portability and build | `__linux__` / `__GLIBC__` guards, GNU extensions, `-lrt -ldl -lpthread`, `-march=native`, hard-coded `gcc`, Linux-only OS detection in Makefile/CMake/configure.ac/meson, sanitizer flags, missing `-lsocket` / `-lfsnotify` |

The scanner understands C: function names inside comments and string literals are not reported (but path strings such as `"/proc/cpuinfo"` are
matched as strings), and code already inside a Linux-only `#if __linux__` branch is reported as `info` ("make sure a QNX branch exists") instead of as a defect.
Quoted includes (`#include "linux/foo.h"`) are treated as project headers. Accepted cases can be silenced in the source with `// qnxport:ignore QNX001`
(next line or same line) or `// qnxport:ignore-file`.

### Accuracy policy (read this)

Every rule has a **confidence**:

* `documented`: the QNX 8.0 documentation has a page for the replacement and states the behaviour the advice relies on (page linked in the report).
* `verify`: the strategy is likely right but could not be confirmed from the public documentation. The report says **"VERIFY on your SDP"**.

"Not in the QNX 8.0 C Library Reference" means *no page was found for that function*; it does not claim the symbol is absent from your SDP headers.
The compiler is the judge. `scripts/verify_doc_links.py` re-checks that all 49 documentation links resolve (all did on 2026-11-06).
Rules were written from the public documentation only; nothing was run on QNX (see "Limits" below).

## Terminal output

Real output (`qnxport scan` on 20 files of Redis 7.2.4; the full reports are in [examples/](examples/)):

```text
qnxport 0.1.0 - QNX 8.0 porting scan
scanned  redis-7.2.4: 20 source files, 31,923 lines, 1 build files
findings 34 high | 43 medium | 17 low | 14 info (info = already inside a Linux-only #if branch, or advice)  [12 rules, 108 findings]

SEV     RULE    COUNT  FILES  WHAT
HIGH    QNX001  21     1      epoll event loop
HIGH    QNX013  9      4      /proc paths (Linux layout)  [verify]
HIGH    QNX008  6      1      CPU affinity
HIGH    QNX035  1      1      systemd / udev integration  [verify]
MEDIUM  QNX019  38     10     Linux/glibc preprocessor guards  [verify]
MEDIUM  QNX020  10     4      glibc / GNU extensions  [verify]
MEDIUM  QNX023  1      1      accept4 / dup3 / SOCK_* creation flags  [verify]
LOW     QNX101  11     1      Linux link flags (-lrt -ldl -lpthread)  [verify]
LOW     QNX105  6      1      sanitizers and Linux-only linker flags  [verify]
INFO    QNX007  3      1      prctl()  [verify]
INFO    QNX024  1      1      Linux file-sync and allocation extensions
INFO    QNX027  1      1      Linux-only mmap/madvise options  [verify]

QNX001  epoll event loop  (21 findings)  [documented in QNX 8.0 docs]
  src/ae_epoll.c:32  #include <sys/epoll.h>
  src/ae_epoll.c:36  struct epoll_event
  src/ae_epoll.c:43  struct epoll_event
  ... and 18 more (see the Markdown/JSON/SARIF report)
  QNX 8.0: Use poll()/ppoll()/select() when you only wait on file descriptors. Use ionotify() with a
    SIGEV_PULSE event (registered with MsgRegisterEvent()) and receive it with MsgReceivePulse()
    when the loop must also serve QNX messages, timers or pulses from other threads. ionotify() arms
    are one-shot: re-arm after every delivery.
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/i/ionotify.html
```
*(file: `docs/snippets/redis-terminal-head.txt`)*

## Reports

| Format | Flag | Use |
|---|---|---|
| terminal | (default; `--brief`, `--quiet`) | quick triage |
| Markdown | `--md FILE` | human report: where to start, per-rule strategy, locations, "to verify on a QNX 8.0 SDP" list |
| JSON | `--json FILE` | scripting / dashboards |
| SARIF 2.1.0 | `--sarif FILE` | GitHub code scanning (`github/codeql-action/upload-sarif`), each result has a stable fingerprint, level (error/warning/note), region and the QNX strategy |
| all three | `--out-dir DIR` | |

The SARIF for the Redis demo was uploaded to this repository's code-scanning API and GitHub reported `processing_status: complete` with no errors (2026-11-06), so the file is accepted by GitHub's SARIF ingestion.

`--fail-on high|medium|low|info` sets a non-zero exit code for CI, `--exclude GLOB` skips vendored code, `--ignore RULE` disables a rule.

## Generators

* `qnxport scaffold DIR` writes `qnx/Makefile.qnx` (qcc based: `CC := qcc -Vgcc_nto$(QNX_ARCH)`, `QNX_ARCH=aarch64le|x86_64`, program/shared library
  detection, `-lsocket` / `-lfsnotify` from the includes it saw) and `qnx-toolchain-aarch64le.cmake` / `qnx-toolchain-x86_64.cmake`
  (`CMAKE_SYSTEM_NAME QNX`, `qcc`/`q++` from `$QNX_HOST`, `CMAKE_<LANG>_COMPILER_TARGET gcc_ntoaarch64le`...).
  The target names come from the qcc documentation. **These are starters: each file says it was generated from the documentation and
  must be checked against your SDP install.** A real example is [tutorial/qnx/Makefile.qnx](tutorial/qnx/Makefile.qnx).
* [examples/github-action/qnxport.yml](examples/github-action/qnxport.yml): a workflow that scans pull requests, fails on new high findings, puts the report in the job summary and uploads the SARIF.

## Demo on real open-source projects

Only the relevant source files were fetched (single files from `raw.githubusercontent.com`, pinned to release tags, [`scripts/fetch_demo_sources.sh`](scripts/fetch_demo_sources.sh));
nothing was cloned and nothing was compiled. The reports are in [examples/](examples/) ([sources and licences](examples/SOURCES.md)).

| Project (files scanned) | Files | Lines | High | Medium | Low | Info | Rules |
|---|---|---|---|---|---|---|---|
| [redis-7.2.4](examples/redis-7.2.4/qnxport-report.md) | 20 | 31,923 | 34 | 43 | 17 | 14 | 12 |
| [libuv-v1.48.0](examples/libuv-v1.48.0/qnxport-report.md) | 13 | 9,757 | 141 | 58 | 12 | 18 | 21 |
| [htop-3.3.0](examples/htop-3.3.0/qnxport-report.md) | 11 | 5,694 | 45 | 11 | 0 | 0 | 11 |

Findings are counts of reported source lines, not estimates of effort. They are the *work list*, not a verdict that a project cannot be ported.

## Tutorial (codelab)

[docs/tutorial-port-epoll-to-qnx8.md](docs/tutorial-port-epoll-to-qnx8.md): port a Linux `epoll` + `timerfd` + `eventfd` event loop to QNX 8.0 twice, once portable
(`poll()` + `pipe()`), once QNX-native (channel, pulses, `timer_create()` + `SIGEV_PULSE`, `ionotify()` + `MsgRegisterEvent()`, `MsgSendPulse()`, `MsgReceivePulse()`),
with complete code, qnxport's real output, a host test of everything that can be tested without QNX, and an explicit checklist of what the reader must verify on a QNX 8.0 target.

## The QNX connection (where to look)

| What | Where |
|---|---|
| The QNX 8.0 knowledge base: for each rule, the Linux construct, the QNX 8.0 API/strategy, its documentation links and a documented/verify flag | [`src/qnxport/rules.py`](src/qnxport/rules.py) (`RULES`, `ADVICE`; helper `lib()` builds the C Library Reference links) |
| Examples of mappings that are checked against the docs: `QNX001` epoll -> `ionotify()`/`MsgReceivePulse()`; `QNX003` timerfd -> `timer_create()` + `SIGEV_PULSE`; `QNX005` inotify -> `-lfsnotify` + `fsevmgr`; `QNX008` affinity -> `ThreadCtl(_NTO_TCTL_RUNMASK)` (calling thread only); `QNX011` memfd -> `shm_open(SHM_ANON)`; `QNX015` `/dev/shm` -> `/dev/shmem`; `QNX016` `/dev/mem` -> `mmap_device_memory()` + `PROCMGR_AID_MEM_PHYS`; `QNX022` `SYS_gettid` -> `gettid()`; `QNX029` capabilities -> `procmgr_ability()` | `rules.py` |
| qcc target selection (`-Vgcc_ntoaarch64le`, `-Vgcc_ntox86_64`), `QNX_HOST` / `QNX_TARGET`, CMake `CMAKE_SYSTEM_NAME QNX` toolchain | [`src/qnxport/generators.py`](src/qnxport/generators.py): `makefile_fragment()`, `cmake_toolchain()`, `write_scaffold()` |
| Findings -> SARIF with QNX strategy and docs link per result | [`src/qnxport/sarif.py`](src/qnxport/sarif.py): `render_sarif()` |
| Static scan (lexer + preprocessor-branch tracking) | [`src/qnxport/scanner.py`](src/qnxport/scanner.py): `blank_c()`, `preprocessor_guard_map()`, `scan_path()` |
| Real QNX 8.0 code (native event loop, written from the docs) | [`tutorial/qnx/loop_qnx.c`](tutorial/qnx/loop_qnx.c): `ChannelCreate`, `ConnectAttach`, `timer_create`+`SIGEV_PULSE_INIT`, `MsgRegisterEvent`, `ionotify`, `MsgSendPulse`, `MsgReceivePulse`, `ChannelDestroy` |
| Portable port that also builds with `qcc` | [`tutorial/portable/loop_poll.c`](tutorial/portable/loop_poll.c) |
| Documentation link checker | [`scripts/verify_doc_links.py`](scripts/verify_doc_links.py) |

## Limits (honest list)

* **Nothing here was run on QNX.** The authors had no QNX 8.0 system. Rules, generators and the tutorial's QNX code were written from the public QNX 8.0 documentation.
  The QNX-native tutorial loop was run on a Linux host against an emulation shim of the QNX calls ([tutorial/hostcheck/](tutorial/hostcheck/)); this checks the loop's logic, not QNX behaviour.
* Static, pattern-based: no preprocessor or type information, so macros that hide a Linux call are missed and shadowed names can be reported. Treat results as a work list.
* Coverage is deliberately limited to constructs we could state accurately. "No finding" does not mean "ports cleanly".
* QNX-specific advice is only as current as the documentation pages dated 2026-11-06; run `scripts/verify_doc_links.py` and re-read a page before relying on a `verify` item.

## Development and tests

```
python -m unittest discover -s tests            # 40 tests: lexer, every rule fires, guards, suppression, SARIF structure, generators, CLI
python scripts/verify_doc_links.py              # needs network
python scripts/build_docs.py                    # regenerate README.md and the tutorial from the *.src.md files
sh scripts/run_examples.sh <fetched-sources>    # regenerate examples/
make -f tutorial/Makefile.host test             # on Linux/WSL: build and run the tutorial programs
```

Pure Python 3 standard library, MIT licensed ([LICENSE](LICENSE)).

---
*Built by Nyx Agents Lab, a team of AI agents (Claude).*
