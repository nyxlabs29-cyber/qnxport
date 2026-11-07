#define _GNU_SOURCE
#include <sched.h>
#include <sys/prctl.h>
#include <sys/sendfile.h>
#include <sys/random.h>
#include <sys/sysinfo.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <sys/inotify.h>
#include <sys/socket.h>
#include <linux/input.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <sys/mman.h>
#include <pthread.h>

void misc(int fd, int out)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(2, &set);
    sched_setaffinity(0, sizeof set, &set);
    prctl(PR_SET_NAME, "worker");
    sendfile(out, fd, 0, 4096);
    char buf[16];
    getrandom(buf, sizeof buf, 0);
    int m = memfd_create("x", MFD_CLOEXEC);
    struct sysinfo si; sysinfo(&si);
    long tid = syscall(SYS_gettid);
    int c = accept4(fd, 0, 0, SOCK_NONBLOCK | SOCK_CLOEXEC);
    fallocate(fd, 0, 0, 1 << 20);
    struct statfs sf; statfs("/", &sf);
    struct timespec ts; clock_gettime(CLOCK_BOOTTIME, &ts);
    void *p = mmap(0, 4096, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
    pthread_yield();
    int ino = inotify_init1(IN_NONBLOCK);
    open("/sys/class/gpio/export", O_WRONLY);
    open("/dev/shm/seg", O_RDWR);
    open("/dev/mem", O_RDWR);
    (void)m; (void)tid; (void)c; (void)p; (void)ino;
}
