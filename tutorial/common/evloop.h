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
