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
