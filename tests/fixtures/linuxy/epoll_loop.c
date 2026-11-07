/* Linux event loop fixture: epoll + timerfd + eventfd + signalfd. */
#define _GNU_SOURCE
#include <stdio.h>
#include <sys/epoll.h>
#include <sys/timerfd.h>
#include <sys/eventfd.h>
#include <sys/signalfd.h>

/* A comment that mentions epoll_wait and sendfile must not be reported. */
static const char *help = "uses epoll_wait() and getrandom()"; /* string: not code */

int run(void)
{
    int ep = epoll_create1(EPOLL_CLOEXEC);
    int tfd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK);
    int efd = eventfd(0, EFD_NONBLOCK);
    sigset_t m;
    int sfd = signalfd(-1, &m, SFD_CLOEXEC);
    struct epoll_event ev = { .events = EPOLLIN | EPOLLET, .data.fd = tfd };
    epoll_ctl(ep, EPOLL_CTL_ADD, tfd, &ev);
    for (;;) {
        struct epoll_event out[8];
        int n = epoll_wait(ep, out, 8, -1);
        (void)n; (void)efd; (void)sfd; (void)help;
    }
}

int cpus(void)
{
    FILE *f = fopen("/proc/cpuinfo", "r");
    FILE *g = fopen("/proc/self/exe", "r");
    (void)g;
    return f != 0;
}
