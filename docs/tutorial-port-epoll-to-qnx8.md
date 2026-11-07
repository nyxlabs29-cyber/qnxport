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

```c
/* The platform-specific half of evdemo. Three implementations exist:
 *   linux/loop_epoll.c    the original Linux program (epoll + timerfd + eventfd)
 *   portable/loop_poll.c  portable POSIX port (poll + pipe), builds on Linux and QNX
 *   qnx/loop_qnx.c        QNX-native port (channel + pulses + ionotify)       */
#ifndef EVLOOP_H
#define EVLOOP_H

#include "evcore.h"

/* Create the loop's resources; tick_ms is the period of the tick event. 0 on success. */
int ev_init(int tick_ms);
/* Thread-safe: tell the loop that background job job_id finished. 0 on success. */
int ev_wake(int job_id);
/* Run until core->quit is set. Returns 0 on success. */
int ev_run(evcore_t *core);
void ev_fini(void);

#endif
```
*(file: `tutorial/common/evloop.h`)*

## 2. Step 1: ask qnxport what is wrong

```sh
pip install .                 # from the qnxport repository root
qnxport scan tutorial/linux
```

Real output of that command:

```text
qnxport 0.1.0 - QNX 8.0 porting scan
scanned  tutorial/linux: 1 source files, 114 lines, 0 build files
findings 14 high | 0 medium | 0 low | 0 info (info = already inside a Linux-only #if branch, or advice)  [3 rules, 14 findings]

SEV     RULE    COUNT  FILES  WHAT
HIGH    QNX001  9      1      epoll event loop
HIGH    QNX003  3      1      timerfd timers
HIGH    QNX002  2      1      eventfd wake-up primitive  [verify]

QNX001  epoll event loop  (9 findings)  [documented in QNX 8.0 docs]
  loop_epoll.c:6  #include <sys/epoll.h>
  loop_epoll.c:19  struct epoll_event
  loop_epoll.c:21  epoll_create1, EPOLL_CLOEXEC
  loop_epoll.c:33  EPOLLIN
  ... and 5 more (see the Markdown/JSON/SARIF report)
  QNX 8.0: Use poll()/ppoll()/select() when you only wait on file descriptors. Use ionotify() with a
    SIGEV_PULSE event (registered with MsgRegisterEvent()) and receive it with MsgReceivePulse()
    when the loop must also serve QNX messages, timers or pulses from other threads. ionotify() arms
    are one-shot: re-arm after every delivery.
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/i/ionotify.html
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/p/poll.html
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/s/select.html

QNX003  timerfd timers  (3 findings)  [documented in QNX 8.0 docs]
  loop_epoll.c:8  #include <sys/timerfd.h>
  loop_epoll.c:22  timerfd_create, TFD_NONBLOCK, TFD_CLOEXEC
  loop_epoll.c:30  timerfd_settime
  QNX 8.0: Create a POSIX timer with timer_create() and a SIGEV_PULSE event, arm it with
    timer_settime(), and receive the pulse with MsgReceivePulse() in the same loop. timer_create()
    accepts CLOCK_REALTIME, CLOCK_MONOTONIC and CLOCK_SOFTTIME. Alternatively derive the poll()
    timeout from your next deadline.
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/t/timer_create.html
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/t/timer_settime.html
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/s/sigevent.html

QNX002  eventfd wake-up primitive  (2 findings)  [VERIFY on your SDP]
  loop_epoll.c:7  #include <sys/eventfd.h>
  loop_epoll.c:23  eventfd, EFD_NONBLOCK, EFD_CLOEXEC
  QNX 8.0: To wake a poll()/select() loop from another thread use a pipe() (documented). In a
    channel/pulse design send a pulse to the loop's channel with MsgSendPulse() instead of an fd
    write.
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/p/pipe.html
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/m/msgsendpulse.html
  docs: https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/topic/m/msgreceivepulse.html
```
*(file: `tutorial/verification/scan-linux.txt`)*

qnxport found the three problems and, for each, the QNX 8.0 strategy with links to the documentation pages it is based on. Note the
wording: the `ionotify()` page itself says the function *"corresponds to the Linux epoll() function and BSD's kqueue()"*, and
`epoll`, `timerfd_*` and `eventfd` have no page in the QNX 8.0 C Library Reference.
Findings tagged `[VERIFY on your SDP]` are strategies that could not be confirmed from the documentation alone.

## 3. Step 2: the Linux original

This is the file qnxport flagged. Read it once; the next two sections replace each of its primitives.

```c
/* LINUX original: epoll + timerfd + eventfd. This is the file qnxport flags. */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <stdint.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/timerfd.h>
#include <time.h>
#include <unistd.h>

#include "../common/evloop.h"

static int g_ep = -1, g_tfd = -1, g_efd = -1;

int ev_init(int tick_ms)
{
    struct itimerspec its;
    struct epoll_event ev;

    g_ep = epoll_create1(EPOLL_CLOEXEC);
    g_tfd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    g_efd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
    if (g_ep < 0 || g_tfd < 0 || g_efd < 0)
        return -1;

    its.it_value.tv_sec = tick_ms / 1000;
    its.it_value.tv_nsec = (long)(tick_ms % 1000) * 1000000L;
    its.it_interval = its.it_value;
    if (timerfd_settime(g_tfd, 0, &its, NULL) < 0)
        return -1;

    ev.events = EPOLLIN;
    ev.data.fd = g_tfd;
    if (epoll_ctl(g_ep, EPOLL_CTL_ADD, g_tfd, &ev) < 0) return -1;
    ev.data.fd = g_efd;
    if (epoll_ctl(g_ep, EPOLL_CTL_ADD, g_efd, &ev) < 0) return -1;
    ev.data.fd = STDIN_FILENO;
    if (epoll_ctl(g_ep, EPOLL_CTL_ADD, STDIN_FILENO, &ev) < 0) return -1;
    return 0;
}

/* eventfd is only the doorbell; the job ids wait in a small mutex-protected queue. */
#define JOBQ_CAP 64
static int g_jobq[JOBQ_CAP];
static int g_jq_head, g_jq_count;
static pthread_mutex_t g_jq_lock = PTHREAD_MUTEX_INITIALIZER;

int ev_wake(int job_id)
{
    uint64_t one = 1;
    pthread_mutex_lock(&g_jq_lock);
    if (g_jq_count == JOBQ_CAP) {
        pthread_mutex_unlock(&g_jq_lock);
        return -1;
    }
    g_jobq[(g_jq_head + g_jq_count++) % JOBQ_CAP] = job_id;
    pthread_mutex_unlock(&g_jq_lock);
    return write(g_efd, &one, sizeof one) == (ssize_t)sizeof one ? 0 : -1;
}

static int jobq_pop(int *job_id)
{
    int ok = 0;
    pthread_mutex_lock(&g_jq_lock);
    if (g_jq_count) {
        *job_id = g_jobq[g_jq_head];
        g_jq_head = (g_jq_head + 1) % JOBQ_CAP;
        g_jq_count--;
        ok = 1;
    }
    pthread_mutex_unlock(&g_jq_lock);
    return ok;
}

int ev_run(evcore_t *core)
{
    struct epoll_event out[8];
    char buf[256];

    while (!core->quit) {
        int i, n = epoll_wait(g_ep, out, 8, -1);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        for (i = 0; i < n && !core->quit; i++) {
            int fd = out[i].data.fd;
            if (fd == g_tfd) {
                uint64_t expirations;
                if (read(g_tfd, &expirations, sizeof expirations) > 0)
                    while (expirations--) evcore_on_tick(core);
            } else if (fd == g_efd) {
                uint64_t cnt;
                int job;
                if (read(g_efd, &cnt, sizeof cnt) > 0)       /* resets the doorbell counter */
                    while (jobq_pop(&job)) evcore_on_job(core, job);
            } else if (fd == STDIN_FILENO) {
                ssize_t r = read(STDIN_FILENO, buf, sizeof buf);
                if (r > 0) evcore_feed(core, buf, (size_t)r);
                else evcore_eof(core);
            }
        }
    }
    return 0;
}

void ev_fini(void)
{
    if (g_ep >= 0) close(g_ep);
    if (g_tfd >= 0) close(g_tfd);
    if (g_efd >= 0) close(g_efd);
}
```
*(file: `tutorial/linux/loop_epoll.c`)*

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

```c
/* PORTABLE POSIX port: poll() + pipe() + a CLOCK_MONOTONIC deadline for the tick.
 * Every call used here has a page in the QNX 8.0 C Library Reference (poll, pipe,
 * clock_gettime, fcntl, read, write), so this file is meant to build with qcc unchanged.
 * It is also what you would ship if the same source tree must keep building on Linux and QNX. */
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>

#include "../common/evloop.h"

static int g_pipe[2] = { -1, -1 };      /* worker threads write job ids, the loop reads them */
static long g_tick_ms;
static struct timespec g_next;           /* next tick deadline on CLOCK_MONOTONIC */

static void add_ms(struct timespec *t, long ms)
{
    t->tv_sec += ms / 1000;
    t->tv_nsec += (ms % 1000) * 1000000L;
    if (t->tv_nsec >= 1000000000L) {
        t->tv_sec++;
        t->tv_nsec -= 1000000000L;
    }
}

/* milliseconds until deadline t, rounded up, never negative */
static int ms_until(const struct timespec *t)
{
    struct timespec now;
    long ms;
    clock_gettime(CLOCK_MONOTONIC, &now);
    ms = (long)(t->tv_sec - now.tv_sec) * 1000L + (t->tv_nsec - now.tv_nsec + 999999L) / 1000000L;
    return ms < 0 ? 0 : (int)ms;
}

int ev_init(int tick_ms)
{
    int fl;
    if (pipe(g_pipe) < 0)
        return -1;
    fl = fcntl(g_pipe[0], F_GETFL, 0);
    if (fl < 0 || fcntl(g_pipe[0], F_SETFL, fl | O_NONBLOCK) < 0)
        return -1;
    g_tick_ms = tick_ms;
    clock_gettime(CLOCK_MONOTONIC, &g_next);
    add_ms(&g_next, g_tick_ms);
    return 0;
}

int ev_wake(int job_id)
{
    /* writes of <= PIPE_BUF bytes are atomic, so concurrent workers never interleave */
    return write(g_pipe[1], &job_id, sizeof job_id) == (ssize_t)sizeof job_id ? 0 : -1;
}

int ev_run(evcore_t *core)
{
    char buf[256];

    while (!core->quit) {
        struct pollfd fds[2];
        int rc;

        fds[0].fd = STDIN_FILENO; fds[0].events = POLLIN; fds[0].revents = 0;
        fds[1].fd = g_pipe[0];    fds[1].events = POLLIN; fds[1].revents = 0;

        rc = poll(fds, 2, ms_until(&g_next));
        if (rc < 0) {
            if (errno == EINTR) continue;
            return -1;
        }

        while (ms_until(&g_next) == 0 && !core->quit) {   /* tick(s) due; catches up after a stall */
            evcore_on_tick(core);
            add_ms(&g_next, g_tick_ms);
        }
        if (fds[1].revents & POLLIN) {
            int job;
            while (read(g_pipe[0], &job, sizeof job) == (ssize_t)sizeof job)
                evcore_on_job(core, job);
        }
        if (fds[0].revents & (POLLIN | POLLHUP)) {
            ssize_t n = read(STDIN_FILENO, buf, sizeof buf);
            if (n > 0) evcore_feed(core, buf, (size_t)n);
            else evcore_eof(core);
        }
    }
    return 0;
}

void ev_fini(void)
{
    if (g_pipe[0] >= 0) close(g_pipe[0]);
    if (g_pipe[1] >= 0) close(g_pipe[1]);
}
```
*(file: `tutorial/portable/loop_poll.c`)*

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

```c
/* QNX 8.0 NATIVE port: one channel, everything arrives as a pulse.
 *
 *   tick   : timer_create() + SIGEV_PULSE  -> pulse CODE_TICK   (the kernel delivers it)
 *   job    : MsgSendPulse() from any thread -> pulse CODE_JOB    (replaces eventfd)
 *   stdin  : ionotify() + SIGEV_PULSE       -> pulse CODE_STDIN  (replaces epoll on fd 0)
 *
 * The loop is a single MsgReceivePulse() call, the QNX counterpart of epoll_wait().
 * Written from the QNX 8.0 documentation; docs/tutorial-port-epoll-to-qnx8.md says what was
 * verified on the host and what you must check on a QNX 8.0 target. */
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <sys/iomsg.h>
#include <sys/neutrino.h>
#include <time.h>
#include <unistd.h>

#include "../common/evloop.h"

enum {
    CODE_TICK = _PULSE_CODE_MINAVAIL,   /* documented safe range: _PULSE_CODE_MINAVAIL .. _PULSE_CODE_MAXAVAIL */
    CODE_JOB,
    CODE_STDIN
};

static int g_chid = -1;                  /* our private channel */
static int g_coid = -1;                  /* connection to it, used to deliver pulses to ourselves */
static timer_t g_timer;
static int g_timer_created;
static struct sigevent g_stdin_ev;       /* registered event handle for ionotify() */
static int g_stdin_registered;

int ev_init(int tick_ms)
{
    struct sigevent ev;
    struct itimerspec its;

    /* Private channel: other processes cannot attach to it, and this process does not need
     * the PROCMGR_AID_PUBLIC_CHANNEL ability (see the ChannelCreate() page). */
    g_chid = ChannelCreate(_NTO_CHF_PRIVATE);
    if (g_chid == -1)
        return -1;

    /* _NTO_SIDE_CHANNEL keeps the connection id out of the file-descriptor number space
     * (recommended on the ConnectAttach() page). */
    g_coid = ConnectAttach(0, 0, g_chid, _NTO_SIDE_CHANNEL, 0);
    if (g_coid == -1)
        return -1;

    /* 1. Periodic tick: the kernel sends the pulse when the timer expires. */
    SIGEV_PULSE_INIT(&ev, g_coid, SIGEV_PULSE_PRIO_INHERIT, CODE_TICK, 0);
    if (timer_create(CLOCK_MONOTONIC, &ev, &g_timer) == -1)
        return -1;
    g_timer_created = 1;
    its.it_value.tv_sec = tick_ms / 1000;
    its.it_value.tv_nsec = (long)(tick_ms % 1000) * 1000000L;
    its.it_interval = its.it_value;
    if (timer_settime(g_timer, 0, &its, NULL) == -1)
        return -1;

    /* 2. stdin readiness: a *server* (the resource manager behind fd 0) will deliver this
     * event, so it must be registered first (MsgRegisterEvent() page). The coid passed to
     * MsgRegisterEvent() is the server's connection, i.e. the file descriptor. */
    SIGEV_PULSE_INIT(&g_stdin_ev, g_coid, SIGEV_PULSE_PRIO_INHERIT, CODE_STDIN, 0);
    if (MsgRegisterEvent(&g_stdin_ev, STDIN_FILENO) == -1)
        return -1;
    g_stdin_registered = 1;
    return 0;
}

int ev_wake(int job_id)
{
    /* Non-blocking, callable from any thread of this process. priority -1 = caller's priority. */
    return MsgSendPulse(g_coid, -1, CODE_JOB, job_id) == -1 ? -1 : 0;
}

/* ionotify() arms are one-shot: after a CODE_STDIN pulse we must read what is there and
 * arm again. _NOTIFY_ACTION_POLLARM returns the conditions that are already true and only
 * arms the event when none is true, so we loop until it arms. */
static void service_stdin(evcore_t *core)
{
    char buf[256];

    while (!core->quit) {
        int rc = ionotify(STDIN_FILENO, _NOTIFY_ACTION_POLLARM, _NOTIFY_COND_INPUT, &g_stdin_ev);
        ssize_t n;
        if (rc == -1) {                      /* e.g. ENOSYS: the manager behind fd 0 does not support it */
            evcore_eof(core);
            return;
        }
        if (!(rc & _NOTIFY_COND_INPUT))
            return;                          /* armed: a CODE_STDIN pulse will arrive */
        n = read(STDIN_FILENO, buf, sizeof buf);   /* input (or EOF) is available: read() will not block */
        if (n > 0)
            evcore_feed(core, buf, (size_t)n);
        else
            evcore_eof(core);
    }
}

int ev_run(evcore_t *core)
{
    service_stdin(core);                     /* arm, and consume anything already waiting */

    while (!core->quit) {
        struct _pulse p;
        if (MsgReceivePulse(g_chid, &p, sizeof p, NULL) == -1) {
            if (errno == EINTR)
                continue;
            return -1;
        }
        switch (p.code) {
        case CODE_TICK:  evcore_on_tick(core); break;
        case CODE_JOB:   evcore_on_job(core, p.value.sival_int); break;
        case CODE_STDIN: service_stdin(core); break;
        default: break;                      /* kernel/manager pulses (negative codes) are ignored here */
        }
    }
    return 0;
}

void ev_fini(void)
{
    if (g_stdin_registered)                  /* _NOTIFY_ACTION_POLL cancels outstanding notifications */
        ionotify(STDIN_FILENO, _NOTIFY_ACTION_POLL, _NOTIFY_COND_INPUT, NULL);
    if (g_timer_created)
        timer_delete(g_timer);
    if (g_coid != -1)
        ConnectDetach(g_coid);
    if (g_chid != -1)
        ChannelDestroy(g_chid);
}
```
*(file: `tutorial/qnx/loop_qnx.c`)*

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

```make
# STARTER FILE generated by qnxport 0.1.0. Written from the public QNX 8.0 documentation; NOT run
# against a QNX SDP by the authors. Check every name and path against your installed SDP.
#
# Usage (after sourcing your SDP environment script, which sets QNX_HOST and QNX_TARGET):
#   make -f Makefile.qnx QNX_ARCH=aarch64le     # or QNX_ARCH=x86_64
#
# qcc selects the target with -V<compiler>_<target>, e.g. -Vgcc_ntoaarch64le or -Vgcc_ntox86_64
# (see 'qcc -V' for the list installed on your host).

NAME      := evdemo
QNX_ARCH ?= aarch64le
ifeq ($(filter $(QNX_ARCH),aarch64le x86_64),)
$(error QNX_ARCH must be aarch64le or x86_64, got '$(QNX_ARCH)')
endif
ifneq ($(MAKECMDGOALS),clean)
ifeq ($(QNX_TARGET),)
$(error QNX_TARGET is not set: source the SDP environment script (qnxsdp-env.sh) first)
endif
endif

QCC_TARGET      := gcc_nto$(QNX_ARCH)
# C++ variant name: confirm with 'qcc -V' (the docs list gcc_nto<arch>_cxx and gcc_nto<arch>_gpp).
QCC_TARGET_CXX  ?= $(QCC_TARGET)_cxx
CC              := qcc -V$(QCC_TARGET)
CXX             := q++ -V$(QCC_TARGET_CXX)
BUILD_DIR       := build/qnx-$(QNX_ARCH)

CPPFLAGS += -DQNXPORT=1
CFLAGS   += -Wall -O2 -g
CXXFLAGS += -Wall -O2 -g
# Detected from #include lines (see the qnxport report):
# (no extra libraries detected)

# Heuristic: files under bench/benchmark/benchmarks/contrib/doc/docs/example/examples/fuzz/samples/test/testing/tests/tools were left out.
COMMON_C   := common/evcore.c \
              qnx/loop_qnx.c
COMMON_CXX := 
COMMON_OBJ := $(COMMON_C:%.c=$(BUILD_DIR)/%.o) $(foreach f,$(COMMON_CXX),$(BUILD_DIR)/$(basename $(f)).o)

# One program per file that defines main():
PROGRAMS := evdemo

.PHONY: all clean
all: $(addprefix $(BUILD_DIR)/,$(PROGRAMS))

$(BUILD_DIR)/evdemo: $(BUILD_DIR)/common/main.o $(COMMON_OBJ)
	$(CC) $(LDFLAGS) -o $@ $^ $(LDLIBS)

$(BUILD_DIR)/%.o: %.c
	@mkdir -p $(@D)
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c -o $@ $<

$(BUILD_DIR)/%.o: %.c++
	@mkdir -p $(@D)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c -o $@ $<

$(BUILD_DIR)/%.o: %.cc
	@mkdir -p $(@D)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c -o $@ $<

$(BUILD_DIR)/%.o: %.cpp
	@mkdir -p $(@D)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c -o $@ $<

$(BUILD_DIR)/%.o: %.cxx
	@mkdir -p $(@D)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -MMD -MP -c -o $@ $<

clean:
	rm -rf build/qnx-aarch64le build/qnx-x86_64

-include $(shell find $(BUILD_DIR) -name '*.d' 2>/dev/null)
```
*(file: `tutorial/qnx/Makefile.qnx`)*

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

```text
# host: Linux 6.6.87.2-microsoft-standard-WSL2 / cc (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0
# command: make -f Makefile.host clean test
mkdir -p build/host
cc -std=gnu99 -Wall -Wextra -O2 -g -o build/host/evdemo-epoll common/evcore.c common/main.c linux/loop_epoll.c -lpthread -lrt
cc -std=gnu99 -Wall -Wextra -O2 -g -o build/host/evdemo-poll common/evcore.c common/main.c portable/loop_poll.c -lpthread -lrt
cc -std=gnu99 -Wall -Wextra -O2 -g -Ihostcheck/include -o build/host/evdemo-qnx-shim common/evcore.c common/main.c qnx/loop_qnx.c hostcheck/neutrino_shim.c -lpthread -lrt
cc -std=gnu99 -Wall -Wextra -O2 -g -o build/host/test_evcore test/test_evcore.c common/evcore.c
build/host/test_evcore
test_evcore: ok
sh test/run_scenarios.sh build/host
PASS evdemo-epoll (ticks seen: 5)
PASS evdemo-poll (ticks seen: 5)
PASS evdemo-qnx-shim (ticks seen: 5)
PASS evdemo-qnx-shim (stdin EOF ends loop)
```
*(file: `tutorial/verification/host-test-output.txt`)*

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

```text
qnxport 0.1.0 - QNX 8.0 porting scan
scanned  tutorial/portable: 1 source files, 98 lines, 0 build files
findings 0 high | 0 medium | 0 low | 0 info (info = already inside a Linux-only #if branch, or advice)  [0 rules, 0 findings]

No Linux-specific constructs from the rule set were found.
```
*(file: `tutorial/verification/scan-portable.txt`)*
```text
qnxport 0.1.0 - QNX 8.0 porting scan
scanned  tutorial/qnx: 1 source files, 133 lines, 2 build files
findings 0 high | 0 medium | 0 low | 0 info (info = already inside a Linux-only #if branch, or advice)  [0 rules, 0 findings]

No Linux-specific constructs from the rule set were found.
```
*(file: `tutorial/verification/scan-qnx.txt`)*

A clean scan means only that none of the Linux-specific constructs in qnxport's rule set remain. It is not a build or test result.

## 11. Where to go next

* Add a TCP listening socket: `poll()` handles it in Option A; in Option B arm it with `ionotify()` like stdin (the ionotify page notes that for a listening socket "input" means a connection is ready to `accept()`).
* Make a resource manager or a message-passing server out of the loop: use `MsgReceive()` and `MsgReply()` and keep pulses for timers.
* Add the CI workflow from `examples/github-action/qnxport.yml` so new Linux-only code is caught on pull requests.

---
*Built by Nyx Agents Lab, a team of AI agents (Claude).*
