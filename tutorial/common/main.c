/* evdemo: tick + background jobs + stdin lines, on top of whichever loop is linked in.
 *
 *   usage: evdemo [tick_ms] [jobs] [job_interval_ms]
 *   defaults: 100 3 150
 */
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#include "evcore.h"
#include "evloop.h"

static int g_jobs = 3;
static int g_interval_ms = 150;
static volatile int g_stop;

static void sleep_ms(int ms)
{
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (long)(ms % 1000) * 1000000L;
    nanosleep(&ts, NULL);
}

static void *worker(void *arg)
{
    int i;
    (void)arg;
    for (i = 1; i <= g_jobs && !g_stop; i++) {
        sleep_ms(g_interval_ms);
        if (g_stop || ev_wake(i) != 0)
            break;
    }
    return NULL;
}

int main(int argc, char **argv)
{
    int tick_ms = argc > 1 ? atoi(argv[1]) : 100;
    pthread_t th;
    evcore_t core;
    int rc;

    if (argc > 2) g_jobs = atoi(argv[2]);
    if (argc > 3) g_interval_ms = atoi(argv[3]);
    if (tick_ms <= 0) tick_ms = 100;

    evcore_init(&core, stdout);
    if (ev_init(tick_ms) != 0) {
        perror("ev_init");
        return 1;
    }
    if (pthread_create(&th, NULL, worker, NULL) != 0) {
        perror("pthread_create");
        ev_fini();
        return 1;
    }
    rc = ev_run(&core);
    g_stop = 1;
    pthread_join(th, NULL);
    ev_fini();
    evcore_summary(&core);
    return rc;
}
