/* evcore: the platform-independent part of the evdemo event loop.
 *
 * Nothing in here knows about epoll, poll() or QNX. It receives three kinds of
 * events (a periodic tick, a finished background job, bytes from standard
 * input) and prints what it did. This is the code you do NOT have to port. */
#ifndef EVCORE_H
#define EVCORE_H

#include <stddef.h>
#include <stdio.h>

typedef struct evcore {
    unsigned ticks;       /* number of tick events handled */
    unsigned jobs;        /* number of job-done events handled */
    unsigned lines;       /* number of input lines handled (the "quit" line is not counted) */
    int quit;             /* set to 1 when the loop should stop */
    FILE *out;            /* where events are reported (stdout by default) */
    char buf[256];        /* partial input line */
    size_t used;
} evcore_t;

void evcore_init(evcore_t *c, FILE *out);
void evcore_on_tick(evcore_t *c);
void evcore_on_job(evcore_t *c, int job_id);
/* Feed bytes read from stdin. Complete lines are upper-cased and reported;
 * the line "quit" stops the loop. */
void evcore_feed(evcore_t *c, const char *data, size_t n);
/* End of input: flush a partial line and stop the loop. */
void evcore_eof(evcore_t *c);
void evcore_summary(const evcore_t *c);

#endif
