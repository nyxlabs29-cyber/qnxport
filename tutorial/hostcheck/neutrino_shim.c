/* HOST EMULATION SHIM implementation: see hostcheck/include/sys/neutrino.h. Linux host only. */
#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>

#include <sys/neutrino.h>
#undef timer_create

#define MAX_CHAN 8
#define QCAP 1024
#define SHIM_NOTIFY 0x51   /* private sigev_notify value marking an emulated pulse event */

struct spec { int coid; int code; long value; };

struct chan {
    int used;
    struct _pulse q[QCAP];
    int head, count;
    pthread_mutex_t lock;
    pthread_cond_t cv;
};

static struct chan g_chan[MAX_CHAN];
static pthread_mutex_t g_tab = PTHREAD_MUTEX_INITIALIZER;
static volatile unsigned g_arm_gen;       /* bumped to cancel emulated ionotify watchers */

static struct chan *by_chid(int chid)
{
    return (chid >= 1 && chid <= MAX_CHAN && g_chan[chid - 1].used) ? &g_chan[chid - 1] : NULL;
}

int ChannelCreate(unsigned flags)
{
    int i;
    (void)flags;
    pthread_mutex_lock(&g_tab);
    for (i = 0; i < MAX_CHAN; i++) {
        if (!g_chan[i].used) {
            memset(&g_chan[i], 0, sizeof g_chan[i]);
            pthread_mutex_init(&g_chan[i].lock, NULL);
            pthread_cond_init(&g_chan[i].cv, NULL);
            g_chan[i].used = 1;
            pthread_mutex_unlock(&g_tab);
            return i + 1;
        }
    }
    pthread_mutex_unlock(&g_tab);
    errno = EAGAIN;
    return -1;
}

int ChannelDestroy(int chid)
{
    struct chan *c = by_chid(chid);
    if (!c) { errno = ESRCH; return -1; }
    c->used = 0;
    return 0;
}

int ConnectAttach(uint32_t nd, int pid, int chid, unsigned index, int flags)
{
    (void)nd; (void)pid; (void)index; (void)flags;
    if (!by_chid(chid)) { errno = ESRCH; return -1; }
    return 1000 + chid;                    /* connection ids live in their own number space */
}

int ConnectDetach(int coid) { (void)coid; return 0; }

int MsgSendPulse(int coid, int priority, int code, long value)
{
    struct chan *c = by_chid(coid - 1000);
    struct _pulse *p;
    (void)priority;
    if (!c) { errno = EBADF; return -1; }
    pthread_mutex_lock(&c->lock);
    if (c->count == QCAP) { pthread_mutex_unlock(&c->lock); errno = EAGAIN; return -1; }
    p = &c->q[(c->head + c->count++) % QCAP];
    memset(p, 0, sizeof *p);
    p->code = (int8_t)code;
    p->value.sival_ptr = (void *)(intptr_t)value;     /* low 32 bits are what sival_int reads on a little-endian host */
    pthread_cond_signal(&c->cv);
    pthread_mutex_unlock(&c->lock);
    return 0;
}

int MsgReceivePulse(int chid, void *pulse, size_t bytes, void *info)
{
    struct chan *c = by_chid(chid);
    (void)info;
    if (!c) { errno = ESRCH; return -1; }
    if (bytes < sizeof(struct _pulse)) { errno = EFAULT; return -1; }
    pthread_mutex_lock(&c->lock);
    while (c->count == 0)
        pthread_cond_wait(&c->cv, &c->lock);
    memcpy(pulse, &c->q[c->head], sizeof(struct _pulse));
    c->head = (c->head + 1) % QCAP;
    c->count--;
    pthread_mutex_unlock(&c->lock);
    return 0;
}

void shim_pulse_init(struct sigevent *ev, int coid, int priority, int code, long value)
{
    struct spec *s = malloc(sizeof *s);                /* intentionally never freed: a few bytes per event */
    (void)priority;
    memset(ev, 0, sizeof *ev);
    s->coid = coid; s->code = code; s->value = value;
    ev->sigev_notify = SHIM_NOTIFY;
    ev->sigev_value.sival_ptr = s;
}

int MsgRegisterEvent(struct sigevent *event, int coid)
{
    (void)event; (void)coid;                           /* the real call turns the event into a kernel handle */
    return 0;
}

static void send_spec(const struct spec *s) { MsgSendPulse(s->coid, -1, s->code, s->value); }

static void timer_fire(union sigval sv) { send_spec((const struct spec *)sv.sival_ptr); }

int shim_timer_create(clockid_t clk, struct sigevent *ev, timer_t *id)
{
    struct sigevent real;
    if (ev->sigev_notify != SHIM_NOTIFY) { errno = EINVAL; return -1; }
    memset(&real, 0, sizeof real);
    real.sigev_notify = SIGEV_THREAD;
    real.sigev_notify_function = timer_fire;
    real.sigev_value = ev->sigev_value;
    return timer_create(clk, &real, id);
}

struct watch { int fd; const struct spec *spec; unsigned gen; };

static void *watcher(void *arg)
{
    struct watch w = *(struct watch *)arg;
    struct pollfd p;
    free(arg);
    p.fd = w.fd; p.events = POLLIN; p.revents = 0;
    poll(&p, 1, -1);
    if (w.gen == g_arm_gen)                            /* not cancelled meanwhile */
        send_spec(w.spec);
    return NULL;
}

int ionotify(int fd, int action, int flags, const struct sigevent *event)
{
    struct pollfd p;
    pthread_t th;
    struct watch *w;
    if (action == _NOTIFY_ACTION_POLL && event == NULL) {   /* disarm */
        g_arm_gen++;
        return 0;
    }
    if (action != _NOTIFY_ACTION_POLLARM || !(flags & _NOTIFY_COND_INPUT) || !event) {
        errno = EINVAL;
        return -1;
    }
    p.fd = fd; p.events = POLLIN; p.revents = 0;
    if (poll(&p, 1, 0) > 0 && (p.revents & (POLLIN | POLLHUP)))
        return _NOTIFY_COND_INPUT;                     /* condition already true: do not arm */
    w = malloc(sizeof *w);
    w->fd = fd; w->spec = (const struct spec *)event->sigev_value.sival_ptr; w->gen = g_arm_gen;
    if (pthread_create(&th, NULL, watcher, w) != 0) { free(w); errno = ENOMEM; return -1; }
    pthread_detach(th);
    return 0;
}
