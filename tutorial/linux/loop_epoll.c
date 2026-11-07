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
