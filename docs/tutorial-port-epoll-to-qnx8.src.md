# Codelab: port a Linux epoll/eventfd/timerfd event loop to QNX OS 8.0

**What you will learn:** how to replace the three Linux event primitives that most daemons are built on
(`epoll`, `timerfd`, `eventfd`) with QNX OS 8.0 equivalents, in two ways:

* **Option A, portable:** `poll()` + `pipe()` + a monotonic deadline. Plain POSIX, builds on Linux and QNX.
* **Option B, QNX-native:** one channel, one `MsgReceivePulse()` loop, timers and file descriptors that deliver
  **pulses** (`timer_create()` + `SIGEV_PULSE`, `ionotify()` + `SIGEV_PULSE`, `MsgSendPulse()`).

**Time:** about 45 minutes. **You need:** a QNX Software Development Platform 8.0 install (host tools, `qcc`) and a QNX 8.0
target or VM to run the result. A Linux machine with a C compiler is optional, for the host tests.

**You will use:** [`qnxport`](../README.md) (the host-side scanner in this repository) to find the problems and to generate
the build files.

---

## 0. What was verified, and what you must verify

This tutorial was written by AI agents without access to a QNX 8.0 system. Please read this box before you trust any line of it.

| Claim | Status |
|---|---|
| Every QNX function and flag used was looked up on its page in the public **QNX 8.0 documentation** (links below), except the fields of `struct _pulse`, whose page was not reachable (see section 8) | Done, 2026-11-06 |
| The shared core (`common/evcore.c`) compiles as plain C and passes its unit test | **Verified on a Linux host** (output in section 9) |
| The Linux original (epoll) and the portable port (poll) build with `-Wall -Wextra` and produce identical output for the same input | **Verified on a Linux host** (section 9) |
| The QNX-native loop (`qnx/loop_qnx.c`) compiles without warnings and its control flow (arm, re-arm, pulse dispatch, shutdown) works | **Verified on a Linux host only against an emulation shim** that I wrote from the documentation (`tutorial/hostcheck/`). The shim is not the QNX kernel. |
| The QNX-native loop builds with `qcc` and runs correctly on QNX 8.0 | **NOT verified. You must do this** (section 8 is the checklist) |
| Performance, latency, or any comparison between options | **Not measured. No numbers are claimed.** |

If something in section 8 behaves differently on your target, trust your target and the QNX documentation, not this text.

## 1. The program

`evdemo` is deliberately small but has the three inputs of a real daemon:

| Input | What happens |
|---|---|
| A periodic **tick** (default every 100 ms) | prints `tick N` |
| A **background worker thread** that finishes 3 jobs | prints `job N done` (the worker must wake the event loop) |
| **Lines on standard input** | prints `line: <UPPERCASED>`; the line `quit` (or end of input) ends the program |

The code is split so that only one file per platform has to change:

```
common/evcore.[ch]   platform-independent: what to do on tick / job / input     (no porting needed)
common/main.c        starts the worker thread, runs the loop                    (no porting needed)
common/evloop.h      the 4-function interface every loop implements:
                     ev_init(), ev_wake(), ev_run(), ev_fini()
linux/loop_epoll.c   original Linux loop: epoll + timerfd + eventfd
portable/loop_poll.c Option A: poll() + pipe()
qnx/loop_qnx.c       Option B: channel + pulses
```

The interface everything plugs into:

<!-- include: tutorial/common/evloop.h -->

## 2. Step 1: ask qnxport what is wrong

```sh
pip install .                 # from the qnxport repository root
qnxport scan tutorial/linux
```

Real output of that command:

<!-- include: tutorial/verification/scan-linux.txt -->

qnxport found the three problems and, for each, the QNX 8.0 strategy with links to the documentation pages it is based on. Note the
wording: the `ionotify()` page itself says the function *"corresponds to the Linux epoll() function and BSD's kqueue()"*, and
`epoll`, `timerfd_*` and `eventfd` have no page in the QNX 8.0 C Library Reference.
Findings tagged `[VERIFY on your SDP]` are strategies that could not be confirmed from the documentation alone.

## 3. Step 2: the Linux original

This is the file qnxport flagged. Read it once; the next two sections replace each of its primitives.

<!-- include: tutorial/linux/loop_epoll.c -->

Three jobs are done by three descriptors:

* `timerfd` produces the tick,
* `eventfd` is the *doorbell* a worker rings to wake the loop (the job ids wait in a small mutex-protected queue),
* `epoll` waits for any of the three descriptors (the third is `stdin`).

## 4. Step 3, Option A: a portable port with `poll()`

If your loop only waits on file descriptors and timeouts, you do not need anything QNX-specific. The replacements:

| Linux | Portable replacement |
|---|---|
| `epoll_wait()` over N descriptors | `poll()` over a `struct pollfd` array ([poll](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/p/poll.html)) |
| `timerfd` tick | keep the next deadline on `CLOCK_MONOTONIC`; use the time left as the `poll()` timeout ([clock_gettime](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/c/clock_gettime.html)) |
| `eventfd` doorbell + queue | a `pipe()`; workers write the job id (4 bytes, below `PIPE_BUF`, so writes from several threads never interleave) ([pipe](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/p/pipe.html)) |

<!-- include: tutorial/portable/loop_poll.c -->

Notes on the design:

* The tick loop `while (ms_until(&g_next) == 0)` catches up if the process was stalled, so ticks are never silently lost.
* The pipe's read end is non-blocking, so the loop can drain everything that arrived in one go.
* Every function used here has a page in the QNX 8.0 C Library Reference, so this file is intended to build with `qcc` unchanged.
  It is the right choice when one source tree must keep building for Linux and QNX.
* `FD_SETSIZE`/`select()` caveat does not apply to `poll()`; if you use `select()` instead, read the [select](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/s/select.html) page about `FD_SETSIZE`.

## 5. Step 4, Option B: a QNX-native port with pulses

On QNX the natural event loop is a **channel**: a kernel object a thread receives on. A **pulse** is a small, non-blocking message
(an 8-bit code and a value) that anything can send to a channel: another thread, a timer, or a resource manager that you
armed with `ionotify()`. One `MsgReceivePulse()` call then replaces `epoll_wait()`.
(Background: [Interprocess Communication](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.sys_arch/topic/ipc.html),
[Pulses](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.sys_arch/topic/ipc_Pulses.html).)

| Linux | QNX 8.0 | Documentation |
|---|---|---|
| `epoll_create1()` | `ChannelCreate()` for the loop, `ConnectAttach()` for a connection that can deliver pulses to it | [ChannelCreate](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/c/channelcreate.html), [ConnectAttach](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/c/connectattach.html) |
| `epoll_ctl(ADD)` on a descriptor | `ionotify(fd, _NOTIFY_ACTION_POLLARM, _NOTIFY_COND_INPUT, &event)` with a `SIGEV_PULSE` event | [ionotify](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/i/ionotify.html), [sigevent](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/s/sigevent.html) |
| `EPOLLONESHOT` | this is the default: *"When an event is delivered, it's always disarmed"*, so re-arm after every pulse | ionotify |
| `EPOLLET` | see `_NOTIFY_ACTION_EDGEARM` / `_NOTIFY_ACTION_TRANARM` on the ionotify page; semantics differ, test your drain logic | ionotify |
| `timerfd_create()` + `timerfd_settime()` | `timer_create()` with a `SIGEV_PULSE` event + `timer_settime()` | [timer_create](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/t/timer_create.html), [timer_settime](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/t/timer_settime.html) |
| `eventfd()` write from a thread | `MsgSendPulse(coid, -1, code, value)` from the thread | [MsgSendPulse](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/m/msgsendpulse.html) |
| `epoll_wait()` | `MsgReceivePulse()` | [MsgReceivePulse](https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/m/msgreceivepulse.html) |

The complete loop:

<!-- include: tutorial/qnx/loop_qnx.c -->

Design decisions, and why (each one comes from a documentation page, not from folklore):

1. **`ChannelCreate(_NTO_CHF_PRIVATE)`**: the channel is for internal use, so mark it private. A public channel needs the
   `PROCMGR_AID_PUBLIC_CHANNEL` ability (ChannelCreate page).
2. **`ConnectAttach(..., _NTO_SIDE_CHANNEL, 0)`**: the ConnectAttach page recommends the side-channel flag so the connection id does not
   share the number space of file descriptors. We keep one connection (`g_coid`) and use it for every pulse source.
3. **The timer needs no registration** (timer_create page: *"The event doesn't need to be registered"*); the kernel delivers it.
4. **The `ionotify()` event does need registration.** A resource manager (here whatever serves file descriptor 0) *delivers* it, so it
   is a "secure event": `MsgRegisterEvent(&event, fd)` first, where the second argument is the connection of the server that is allowed to
   send it (the MsgRegisterEvent page: *"The coid argument can contain any type of connection ID, including ... a file descriptor"*).
   Note the page's warning: the coid you give the pulse macro is where the pulse is delivered, the one you give `MsgRegisterEvent()` is the server's.
5. **`service_stdin()` loops.** `_NOTIFY_ACTION_POLLARM` polls first and only arms if no condition is true; it returns the conditions that
   are already true. So: if input is already there, read it (it cannot block) and ask again; once it returns "not ready", the event is armed.
   Without the loop, a re-arm that finds data still waiting would return "ready" without arming anything, and the program would stall until some unrelated pulse arrived.
6. **`MsgSendPulse(coid, -1, ...)`** replaces both `eventfd` and the job queue: the job id *is* the pulse value. Priority `-1` means "use the
   caller's priority" (MsgSendPulse page). The pulse code stays inside the documented safe range `_PULSE_CODE_MINAVAIL .. _PULSE_CODE_MAXAVAIL`.
7. **Negative pulse codes are ignored** (`default:` branch): the kernel and QNX managers use those (`_PULSE_CODE_*`).
8. **Shutdown:** `ionotify(..., _NOTIFY_ACTION_POLL, ..., NULL)` cancels outstanding notifications (documented as the "simple disarm call"),
   then the timer, connection and channel are released.

Choosing between A and B: pick **A** when the loop only needs descriptors and timeouts and you want one source tree. Pick **B** when the same loop
must also receive QNX messages or pulses from other processes (use `MsgReceive()` instead of `MsgReceivePulse()` then), or you want kernel-delivered
timers and priority-aware delivery. `MsgReceivePulse()` receives pulses only; do not use it on a channel that clients send messages to.

## 6. Step 5: let qnxport write the build files

```sh
qnxport scaffold <staging dir with common/ and qnx/> --name evdemo --out tutorial/qnx
```

(`scripts/regen_tutorial_scaffold.sh` does exactly this.) It writes a `qcc`-based Makefile and CMake toolchain files for `aarch64le` and `x86_64`.
They are **starters generated from the documentation**; the header of each file says so. The Makefile:

<!-- include: tutorial/qnx/Makefile.qnx -->

Key facts it relies on (qcc page): the target is chosen with `-V<compiler>_<target>`, for example `qcc -Vgcc_ntoaarch64le` or `qcc -Vgcc_ntox86_64`; run `qcc -V`
to list what your SDP provides. Nothing needs `-lpthread`, `-lrt` or `-ldl`: the pages for `pthread_create()`, `timer_create()` and `dlopen()` list libc, which is linked automatically.

## 7. Step 6: build and run on QNX 8.0

```sh
# on the host where the SDP is installed (this sets QNX_HOST and QNX_TARGET):
source ~/qnx800/qnxsdp-env.sh            # path and script name depend on your install: verify
cd tutorial
make -f qnx/Makefile.qnx QNX_ARCH=aarch64le     # or QNX_ARCH=x86_64
scp build/qnx-aarch64le/evdemo root@<target-ip>:/tmp/
```

On the target:

```sh
cd /tmp
( echo hello; sleep 1; echo world; echo quit ) | ./evdemo 100 3 150
```

The program should print the following **(expected output, taken from the host runs in section 9; ticks vary with timing)**:

```
tick 1
line: HELLO
tick 2
job 1 done
tick 3
...
job 3 done
...
line: WORLD
summary jobs=3 lines=2 ticks_ge_2=1
```

## 8. What you must verify on QNX 8.0

Each item is something the documentation led me to expect but that I could not run. Tick them off:

- [ ] `qcc -Vgcc_ntoaarch64le` (or `x86_64`) compiles `qnx/loop_qnx.c` with no warnings; `qcc -V` lists the targets the Makefile names.
- [ ] `struct _pulse` has the fields used: `code` and `value.sival_int`. (The `_pulse` documentation page was not reachable when this was written;
      the fields come from `<sys/neutrino.h>` conventions.) `MsgSendPulse()`'s value is a 64-bit `long`; the loop reads it as `sival_int`, which is right for
      the little-endian targets (`aarch64le`, `x86_64`) with job ids below 2^31.
- [ ] `ionotify()` is supported by whatever serves fd 0 in your setup (a shell on a serial console, a pipe, a file, ...). If it returns `-1` with `ENOSYS`
      (listed on the ionotify page), the program treats that as end of input and exits; use Option A for such descriptors.
- [ ] `MsgRegisterEvent(&event, STDIN_FILENO)` succeeds for your fd type. If events never arrive, the QNX docs say you can detect unregistered or
      disallowed events with `secpolgenerate` (via `/dev/secpolgenerate/errors`) or `secpolmonitor -u` (MsgRegisterEvent page).
- [ ] Tick pulses keep arriving while stdin is idle, and a burst of input is not lost (feed 1000 lines and compare the count).
- [ ] The process needs no special abilities when run as a normal user. If `ChannelCreate()` or `timer_create()` fail with `EPERM`, check `procmgr_ability()`.
- [ ] Run `./evdemo 100 3 150` with stdin redirected from `/dev/null`: it must exit immediately with `summary jobs=0 ...` (end of input).

## 9. What was actually run (host evidence)

On a Linux host (WSL2, `cc` 13.3.0), `make -f Makefile.host clean test` in `tutorial/`:

<!-- include: tutorial/verification/host-test-output.txt -->

The three programs were fed identical input (`hello`, then after 600 ms `world` and `quit`) and each printed exactly the expected normalised output:
the same `line:` and `job` lines in the same order and a summary of `jobs=3 lines=2`. The tick count is the only timing-dependent value (5 ticks were seen in each run).

What this shows: the shared core is correct; the control flow of `loop_qnx.c` (private channel, pulse per source, the arm / read / re-arm loop for stdin, end-of-input handling, shutdown)
produces the same observable behaviour as the epoll original **when the QNX calls behave as documented**. What it does not show: that they do, on QNX.
The shim emulates a channel with a mutex-protected queue and a condition variable, timers with a POSIX `SIGEV_THREAD` timer, and `ionotify()` with a watcher thread. It is in
`tutorial/hostcheck/` and every file in it says it is not the QNX header.

## 10. Re-scan the ported code

```sh
qnxport scan tutorial/portable
qnxport scan tutorial/qnx
```

<!-- include: tutorial/verification/scan-portable.txt -->
<!-- include: tutorial/verification/scan-qnx.txt -->

A clean scan means only that none of the Linux-specific constructs in qnxport's rule set remain. It is not a build or test result.

## 11. Where to go next

* Add a TCP listening socket: `poll()` handles it in Option A; in Option B arm it with `ionotify()` like stdin (the ionotify page notes that for a listening socket "input" means a connection is ready to `accept()`).
* Make a resource manager or a message-passing server out of the loop: use `MsgReceive()` and `MsgReply()` and keep pulses for timers.
* Add the CI workflow from `examples/github-action/qnxport.yml` so new Linux-only code is caught on pull requests.

---
*Built by Nyx Agents Lab, a team of AI agents (Claude).*
