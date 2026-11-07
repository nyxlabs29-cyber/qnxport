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
