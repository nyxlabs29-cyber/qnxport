/* HOST EMULATION SHIM: NOT the QNX header.
 *
 * This file lets qnx/loop_qnx.c be compiled and RUN on a Linux host so that its control flow
 * (arming, re-arming, pulse dispatch, shutdown) can be tested. Declarations follow the QNX 8.0
 * C Library Reference pages for ChannelCreate, ConnectAttach, MsgSendPulse, MsgReceivePulse,
 * MsgRegisterEvent, ionotify and sigevent. The behaviour is emulated with threads, a mutex and a
 * condition variable. It proves nothing about the QNX kernel: only a QNX 8.0 target can. */
#ifndef QNX_HOST_SHIM_NEUTRINO_H
#define QNX_HOST_SHIM_NEUTRINO_H

#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <time.h>

#define _NTO_CHF_PRIVATE          0x00008000u
#define _NTO_SIDE_CHANNEL         0x40000000u
#define _PULSE_CODE_MINAVAIL      0
#define _PULSE_CODE_MAXAVAIL      127
#define SIGEV_PULSE_PRIO_INHERIT  (-1)

#define _NOTIFY_ACTION_POLL       0
#define _NOTIFY_ACTION_POLLARM    1
#define _NOTIFY_COND_INPUT        0x00000001

struct _pulse {
    uint16_t type;
    uint16_t subtype;
    int8_t code;
    uint8_t zero[3];
    union sigval value;
    int32_t scoid;
};

int ChannelCreate(unsigned flags);
int ChannelDestroy(int chid);
int ConnectAttach(uint32_t nd, int pid, int chid, unsigned index, int flags);
int ConnectDetach(int coid);
int MsgReceivePulse(int chid, void *pulse, size_t bytes, void *info);
int MsgSendPulse(int coid, int priority, int code, long value);
int MsgRegisterEvent(struct sigevent *event, int coid);
int ionotify(int fd, int action, int flags, const struct sigevent *event);

void shim_pulse_init(struct sigevent *ev, int coid, int priority, int code, long value);
int shim_timer_create(clockid_t clk, struct sigevent *ev, timer_t *id);

#define SIGEV_PULSE_INIT(ev, coid, prio, code, value) \
    shim_pulse_init((ev), (coid), (prio), (code), (long)(value))
#define timer_create(clk, ev, id) shim_timer_create((clk), (ev), (id))

#endif
