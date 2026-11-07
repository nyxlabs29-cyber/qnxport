#include <sys/epoll.h> // qnxport:ignore QNX001
int a(void)
{
    // qnxport:ignore QNX001
    int ep = epoll_create1(0);
    int ef = eventfd(0, 0); // qnxport:ignore QNX002
    return ep + ef;
}
