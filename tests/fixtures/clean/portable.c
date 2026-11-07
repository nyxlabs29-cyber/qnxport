#include <poll.h>
#include <unistd.h>
#include <time.h>
#include <pthread.h>
#include <string.h>

#ifdef __QNXNTO__
#include <sys/neutrino.h>
#endif

int wait_readable(int fd, int ms)
{
    struct pollfd p = { fd, POLLIN, 0 };
    return poll(&p, 1, ms);
}

int wake_pipe(int fds[2]) { return pipe(fds); }
