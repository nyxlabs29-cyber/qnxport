#include <stdio.h>
#ifdef __linux__
#include <sys/epoll.h>
int wait_a(int ep) { struct epoll_event e; return epoll_wait(ep, &e, 1, 0); }
#else
#include <poll.h>
int wait_a(int fd) { struct pollfd p = { fd, POLLIN, 0 }; return poll(&p, 1, 0); }
#endif

#ifndef __linux__
int portable(void) { return 0; }
#else
int portable(void) { return eventfd(0, 0); }
#endif

#if defined(__linux__) || defined(__QNXNTO__)
int mixed(void) { return eventfd(0, 0); }
#endif
#include "linux/Platform.h"
