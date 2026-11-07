"""Rule database for qnxport.

Every rule says what Linux/non-QNX construct it detects, how severe the
problem usually is, and what the QNX 8.0 equivalent / porting strategy is.

Accuracy policy
---------------
* ``confidence == "documented"``: the replacement named in ``qnx`` has a page
  in the public QNX 8.0 documentation and the behaviour we rely on is stated
  there (the page is linked in ``docs``).
* ``confidence == "verify"``: we believe the strategy is right but could not
  confirm it from the public QNX 8.0 documentation, or the documentation does
  not list the Linux API at all. The report says "verify" and the reader must
  check against the headers/docs of their installed QNX SDP.

"Not in the QNX 8.0 C Library Reference" means: no page for that function in
https://www.qnx.com/developers/docs/8.0/com.qnx.doc.neutrino.lib_ref/ when this
database was written (2026-11-06). It is not proof that the symbol is absent
from your SDP headers: always confirm with the compiler.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

DOCS_CHECKED = "2026-11-06"

_BASE = "https://www.qnx.com/developers/docs/8.0/"
LIB = _BASE + "com.qnx.doc.neutrino.lib_ref/topic/"
UTIL = _BASE + "com.qnx.doc.neutrino.utilities/topic/"
SYSARCH = _BASE + "com.qnx.doc.neutrino.sys_arch/topic/"
PROG = _BASE + "com.qnx.doc.neutrino.prog/topic/"


def lib(name: str, title: str = "") -> Tuple[str, str]:
    """Link to a C Library Reference page (file names are lower case)."""
    n = name.lower()
    return (title or name + "()", "%s%s/%s.html" % (LIB, n[0], n))


def util(name: str, title: str = "") -> Tuple[str, str]:
    n = name.lower()
    return (title or name, "%s%s/%s.html" % (UTIL, n[0], n))


DOC_QCC = util("qcc", "qcc / q++ (Utilities Reference)")
DOC_PROC = ("Controlling processes via the /proc filesystem (Programmer's Guide)",
            PROG + "process_proc_filesystem.html")
DOC_IPC = ("Interprocess Communication (System Architecture)", SYSARCH + "ipc.html")
DOC_PULSES = ("Pulses (System Architecture)", SYSARCH + "ipc_Pulses.html")


@dataclass
class Rule:
    id: str
    title: str
    category: str
    severity: str          # high | medium | low | info
    confidence: str        # documented | verify
    why: str               # what is wrong on QNX
    qnx: str               # QNX 8.0 equivalent / strategy (one paragraph)
    docs: List[Tuple[str, str]] = field(default_factory=list)
    inc: List[str] = field(default_factory=list)      # regex vs include path
    sym: List[str] = field(default_factory=list)      # regex vs code (comments/strings blanked)
    string: List[str] = field(default_factory=list)   # regex vs string literal contents
    build: List[str] = field(default_factory=list)    # regex vs build-file lines
    notes: List[Tuple[str, str]] = field(default_factory=list)  # (regex vs matched text, extra advice)

    @property
    def kind(self) -> str:
        return "build" if self.build else "source"


RULES: List[Rule] = []


def _r(*a, **k):
    RULES.append(Rule(*a, **k))


# --------------------------------------------------------------------------
# Event notification / fd-like kernel objects
# --------------------------------------------------------------------------
_r("QNX001", "epoll event loop", "events", "high", "documented",
   "epoll has no page in the QNX 8.0 C Library Reference. The ionotify() page states that it "
   "'corresponds to the Linux epoll() function and BSD's kqueue()'.",
   "Use poll()/ppoll()/select() when you only wait on file descriptors. Use ionotify() with a "
   "SIGEV_PULSE event (registered with MsgRegisterEvent()) and receive it with MsgReceivePulse() "
   "when the loop must also serve QNX messages, timers or pulses from other threads. "
   "ionotify() arms are one-shot: re-arm after every delivery.",
   [lib("ionotify"), lib("poll", "poll(), ppoll()"), lib("select", "select(), pselect()"),
    lib("msgreceivepulse", "MsgReceivePulse()"), lib("msgregisterevent", "MsgRegisterEvent()"),
    lib("sigevent", "sigevent")],
   inc=[r"^sys/epoll\.h$"],
   sym=[r"\bepoll_(?:create1?|ctl|p?wait)\b", r"\bstruct\s+epoll_event\b", r"\bEPOLL[A-Z_]*\b"],
   notes=[(r"EPOLLET", "Edge-triggered: see _NOTIFY_ACTION_EDGEARM / _NOTIFY_ACTION_TRANARM in the ionotify() "
                       "page; the semantics are not identical to EPOLLET, so test the drain logic."),
          (r"EPOLLONESHOT", "ionotify() events are disarmed once delivered (see the ionotify() page): re-arm explicitly."),
          (r"epoll_create1?", "Replace the epoll fd with a channel (ChannelCreate()) plus a connection "
                              "(ConnectAttach()) for SIGEV_PULSE_INIT(), or with a pollfd array.")])

_r("QNX002", "eventfd wake-up primitive", "events", "high", "verify",
   "eventfd has no page in the QNX 8.0 C Library Reference.",
   "To wake a poll()/select() loop from another thread use a pipe() (documented). In a "
   "channel/pulse design send a pulse to the loop's channel with MsgSendPulse() instead of an fd write.",
   [lib("pipe"), lib("msgsendpulse", "MsgSendPulse()"), lib("msgreceivepulse", "MsgReceivePulse()")],
   inc=[r"^sys/eventfd\.h$"],
   sym=[r"\beventfd(?:_read|_write)?\b", r"\bEFD_(?:CLOEXEC|NONBLOCK|SEMAPHORE)\b"])

_r("QNX003", "timerfd timers", "events", "high", "documented",
   "timerfd_* has no page in the QNX 8.0 C Library Reference.",
   "Create a POSIX timer with timer_create() and a SIGEV_PULSE event, arm it with timer_settime(), and "
   "receive the pulse with MsgReceivePulse() in the same loop. timer_create() accepts CLOCK_REALTIME, "
   "CLOCK_MONOTONIC and CLOCK_SOFTTIME. Alternatively derive the poll() timeout from your next deadline.",
   [lib("timer_create"), lib("timer_settime"), lib("sigevent", "sigevent"), lib("msgreceivepulse", "MsgReceivePulse()"),
    lib("poll", "poll(), ppoll()")],
   inc=[r"^sys/timerfd\.h$"],
   sym=[r"\btimerfd_(?:create|settime|gettime)\b", r"\bTFD_[A-Z_]+\b"])

_r("QNX004", "signalfd signal delivery", "events", "high", "verify",
   "signalfd has no page in the QNX 8.0 C Library Reference.",
   "Block the signals and collect them with sigwaitinfo()/sigtimedwait() in a dedicated thread, which then "
   "wakes the main loop (pipe write or MsgSendPulse()). For timer expiry prefer SIGEV_PULSE directly.",
   [lib("sigwaitinfo", "sigwaitinfo(), sigtimedwait()"), lib("sigtimedwait"),
    lib("msgsendpulse", "MsgSendPulse()"), lib("sigevent", "sigevent")],
   inc=[r"^sys/signalfd\.h$"],
   sym=[r"\bsignalfd(?:4)?\b", r"\bstruct\s+signalfd_siginfo\b", r"\bSFD_(?:CLOEXEC|NONBLOCK)\b"])

_r("QNX005", "inotify filesystem watches", "events", "medium", "documented",
   "QNX 8.0 documents inotify (libfsnotify), but it is served by the fsevmgr filesystem event manager: "
   "the program must link -lfsnotify, /dev/fsnotify must exist and be readable, and inotify_init() fails "
   "if fsevmgr is not running.",
   "Keep the inotify code, add -lfsnotify to the link line, make sure fsevmgr runs on the target, and handle "
   "inotify_init() failure at start-up. Check event coverage per filesystem on your target (verify). "
   "inotify_qnx_ext() enables QNX-specific extensions.",
   [lib("inotify_init", "inotify_init(), inotify_init1()"), lib("inotify_add_watch"),
    util("fsevmgr")],
   inc=[r"^sys/inotify\.h$"],
   sym=[r"\binotify_(?:init1?|add_watch|rm_watch)\b", r"\bstruct\s+inotify_event\b"])

_r("QNX006", "fanotify", "events", "high", "verify",
   "fanotify has no page in the QNX 8.0 C Library Reference.",
   "Evaluate whether the documented inotify interface (served by fsevmgr) covers the use case; otherwise "
   "a QNX resource manager or filesystem-level hook is needed. No documented one-to-one equivalent: verify.",
   [lib("inotify_init", "inotify_init(), inotify_init1()")],
   inc=[r"^sys/fanotify\.h$"],
   sym=[r"\bfanotify_(?:init|mark)\b", r"\bFAN_[A-Z_]+\b"])

# --------------------------------------------------------------------------
# Process / thread / scheduling
# --------------------------------------------------------------------------
_r("QNX007", "prctl()", "process", "high", "verify",
   "prctl has no page in the QNX 8.0 C Library Reference.",
   "PR_SET_NAME / PR_GET_NAME map to pthread_setname_np(0, name) / pthread_getname_np() (documented; the "
   "length limit is _NTO_THREAD_NAME_MAX instead of Linux's 16 bytes). Other options (PR_SET_PDEATHSIG, "
   "PR_SET_DUMPABLE, PR_SET_NO_NEW_PRIVS, PR_SET_SECCOMP ...) have no documented single-call equivalent: "
   "verify, or use procmgr_ability() for privilege control.",
   [lib("pthread_setname_np"), lib("pthread_getname_np"), lib("procmgr_ability")],
   inc=[r"^sys/prctl\.h$"],
   sym=[r"\bprctl\b", r"\bPR_[A-Z_]{3,}\b"],
   notes=[(r"PR_SET_NAME|PR_GET_NAME", "Direct mapping: pthread_setname_np(0, name) names the calling thread."),
          (r"PR_SET_PDEATHSIG", "No documented equivalent: consider a connection/pulse (_PULSE_CODE_COIDDEATH, "
                                "ChannelCreate flags) to detect the parent going away (verify).")])

_r("QNX008", "CPU affinity", "process", "high", "documented",
   "sched_setaffinity / pthread_setaffinity_np and the CPU_* macros have no page in the QNX 8.0 C Library Reference.",
   "For the calling thread use ThreadCtl(_NTO_TCTL_RUNMASK, &mask) (also _NTO_TCTL_RUNMASK_GET_AND_SET and "
   "_NTO_TCTL_RUNMASK_GET_AND_SET_INHERIT); map CPU numbers to bits of the runmask. The ThreadCtl() page says the "
   "runmask commands can only be executed on the calling thread, so code that sets the affinity of ANOTHER thread or "
   "process (sched_setaffinity(pid, ...)) has no documented equivalent: the target thread must set its own runmask "
   "(verify). sched_getcpu() has no documented equivalent: verify.",
   [lib("threadctl", "ThreadCtl()")],
   sym=[r"\bsched_(?:set|get)affinity\b", r"\bpthread_(?:set|get|attr_set|attr_get)affinity_np\b",
        r"\bcpu_set_t\b", r"\bCPU_(?:SET|ZERO|ISSET|CLR|COUNT|ALLOC|FREE|SETSIZE)(?:_S)?\b", r"\bsched_getcpu\b"])

_r("QNX009", "zero-copy transfer (sendfile/splice/tee)", "io", "high", "verify",
   "sendfile, splice, tee and vmsplice have no page in the QNX 8.0 C Library Reference.",
   "Fall back to a read()/write() loop (or mmap() of the source file). Keep the Linux path behind an "
   "#ifdef and add a portable copy loop. Check your SDP for any BSD-style sendfile() before relying on it (verify).",
   [lib("read"), lib("mmap")],
   inc=[r"^sys/sendfile\.h$"],
   sym=[r"\bsendfile(?:64)?\b", r"\bsplice\b", r"\bvmsplice\b", r"\btee\s*\(\s*\w+\s*,", r"\bSPLICE_F_[A-Z_]+\b"])

_r("QNX010", "getrandom / getentropy / arc4random", "io", "medium", "verify",
   "getrandom, getentropy and arc4random have no page in the QNX 8.0 C Library Reference.",
   "Read from /dev/random (or /dev/urandom) with open()/read(). On QNX these are provided by the 'random' "
   "service, which needs slogger2 running and must be started by root or with the right abilities; handle "
   "short reads and open failure. Check your SDP headers before assuming getentropy() exists (verify).",
   [util("random", "random service (Utilities Reference)"), lib("read")],
   inc=[r"^sys/random\.h$"],
   sym=[r"\bgetrandom\b", r"\bgetentropy\b", r"\barc4random(?:_buf|_uniform)?\b", r"\bGRND_[A-Z]+\b"])

_r("QNX011", "memfd_create", "io", "medium", "documented",
   "memfd_create has no page in the QNX 8.0 C Library Reference.",
   "Use shm_open(SHM_ANON, O_RDWR, mode) for an anonymous shared-memory object (documented: passing "
   "SHM_ANON as the name sets O_ANON and O_CREAT), then ftruncate() and mmap(). Sealing (F_ADD_SEALS) has no "
   "documented equivalent: verify.",
   [lib("shm_open"), lib("mmap")],
   inc=[r"^sys/memfd\.h$"],
   sym=[r"\bmemfd_create\b", r"\bMFD_[A-Z_]+\b", r"\bF_ADD_SEALS\b", r"\bF_SEAL_[A-Z]+\b"])

_r("QNX012", "sysinfo / load / CPU count helpers", "system", "high", "verify",
   "sys/sysinfo.h, sysinfo(), get_nprocs() and getloadavg() have no page in the QNX 8.0 C Library Reference.",
   "sysconf() is documented for configurable limits (page size, open files, ...). For CPU count, memory "
   "totals and uptime check which sysconf names your SDP defines and the system page (<sys/syspage.h>); "
   "there is no documented load-average call (verify).",
   [lib("sysconf")],
   inc=[r"^sys/sysinfo\.h$"],
   sym=[r"\bsysinfo\s*\(", r"\bstruct\s+sysinfo\b", r"\bget_nprocs(?:_conf)?\b", r"\bget_(?:av)?phys_pages\b",
        r"\bgetloadavg\b"])

_r("QNX013", "/proc paths (Linux layout)", "system", "high", "verify",
   "QNX has a /proc, but it is a process-manager namespace with its own layout, not Linux text files such "
   "as /proc/cpuinfo, /proc/meminfo, /proc/stat or /proc/<pid>/stat.",
   "Use the QNX /proc interface (devctl() with DCMD_PROC_* commands) described in the Programmer's Guide, "
   "sysconf(), or pidin-style queries instead of parsing Linux files. For the executable path, QNX provides "
   "/proc/self/exefile (verify on your target).",
   [DOC_PROC, lib("devctl")],
   string=[r"^/proc(?:/|$)"],
   notes=[(r"/proc/self/exe\b", "Linux readlink(\"/proc/self/exe\") -> on QNX read /proc/self/exefile (verify)."),
          (r"/proc/(?:cpuinfo|meminfo|stat|loadavg|uptime)", "System-wide Linux text files: no QNX counterpart in /proc; "
                                                              "use sysconf()/system page APIs (verify)."),
          (r"/proc/net", "Networking state is not exposed through /proc/net on QNX: use the networking APIs (verify).")])

_r("QNX014", "/sys (sysfs) paths", "system", "high", "verify",
   "QNX does not provide Linux sysfs. Paths such as /sys/class/gpio, /sys/class/net or /sys/devices have no QNX counterpart.",
   "Use the QNX driver/resource-manager interface for the device (GPIO, I2C, SPI, networking APIs, ...). "
   "Which one depends on your BSP: verify in the BSP documentation.",
   [lib("devctl")],
   string=[r"^/sys(?:/|$)"])

_r("QNX015", "/dev/shm shared memory", "io", "medium", "documented",
   "POSIX shared memory objects are not under /dev/shm on QNX; the shm_open() page documents /dev/shmem.",
   "Call shm_open()/shm_unlink() and do not hard-code the filesystem path.",
   [lib("shm_open"), lib("shm_unlink")],
   string=[r"^/dev/shm(?:/|$)"])

_r("QNX016", "/dev/mem physical memory access", "io", "high", "documented",
   "/dev/mem is a Linux device node.",
   "Use mmap_device_memory(). The process needs the PROCMGR_AID_MEM_PHYS "
   "ability (see procmgr_ability()); the correct physical addresses come from your BSP.",
   [lib("mmap_device_memory"), lib("procmgr_ability")],
   string=[r"^/dev/(?:mem|kmem|port)$"])

_r("QNX017", "linux/ kernel UAPI headers", "headers", "high", "verify",
   "#include <linux/...> headers (input, videodev2, i2c-dev, spidev, gpio, fb, netlink, ...) describe Linux kernel "
   "interfaces that QNX does not provide.",
   "Identify the device or service behind the header and use the matching QNX interface (resource manager "
   "devctl()/ioctl() commands, Screen, QNX Sound Architecture, hw/ headers of the BSP). The right header is "
   "device specific: verify in the BSP/SDK docs.",
   [lib("devctl"), lib("ioctl", "ioctl(), vioctl()")],
   inc=[r"^linux/.+", r"^asm/.+", r"^asm-generic/.+"])

_r("QNX018", "Linux-specific ioctl requests", "io", "medium", "verify",
   "ioctl request codes such as BLK*, FS_IOC_*, FICLONE, SIOCETHTOOL, EVIOC*, I2C_*/SPI_IOC_* and TUNSETIFF are Linux definitions.",
   "QNX resource managers are usually controlled with devctl() and DCMD_* commands. Map each request to the "
   "corresponding resource-manager command for your driver (verify per driver).",
   [lib("devctl"), lib("ioctl", "ioctl(), vioctl()")],
   sym=[r"\bBLK(?:GETSIZE64?|FLSBUF|SSZGET|BSZGET|DISCARD|ROGET)\b", r"\bFS_IOC_[A-Z_0-9]+\b", r"\bFICLONE(?:RANGE)?\b",
        r"\bSIOCETHTOOL\b", r"\bEVIOC[A-Z]+\b", r"\bI2C_(?:SLAVE|RDWR|SMBUS|FUNCS)\b", r"\bSPI_IOC_[A-Z_]+\b",
        r"\bTUNSETIFF\b", r"\bTIOC(?:G|S)SERIAL\b", r"\bKD(?:SETMODE|GKBMODE)\b", r"\bVT_[A-Z]+\b", r"\bHIDIOC[A-Z]+\b"])

# --------------------------------------------------------------------------
# Platform macros, libc extensions
# --------------------------------------------------------------------------
_r("QNX019", "Linux/glibc preprocessor guards", "portability", "medium", "verify",
   "Code under #ifdef __linux__ / __GLIBC__ is not compiled by qcc for QNX, so such branches silently disappear "
   "and some #else branches may pick a BSD or generic path that was never tested on QNX.",
   "Add an explicit __QNXNTO__ (and/or __QNX__) branch, or restructure so the portable code path is the default. "
   "qcc predefines the QNX macros: confirm with 'qcc -V... -dM -E - < /dev/null' on your SDP (verify).",
   [DOC_QCC],
   sym=[r"\b__linux__\b", r"\b__linux\b", r"\b__gnu_linux__\b", r"\b__GLIBC__\b", r"\b__GNU_LIBRARY__\b",
        r"\b__GLIBC_MINOR__\b", r"\b__KERNEL__\b"])

_r("QNX020", "glibc / GNU extensions", "portability", "medium", "verify",
   "These GNU extensions have no page in the QNX 8.0 C Library Reference (they may still be available in your SDP "
   "headers or not: the compiler is the judge).",
   "Provide a small portable replacement in your own code (strchrnul/memrchr/qsort_r/secure_getenv/"
   "canonicalize_file_name/get_current_dir_name are a few lines each), or guard the use. Do not assume the "
   "glibc behaviour (verify).",
   [lib("realpath"), lib("getopt_long")],
   inc=[r"^argp\.h$", r"^obstack\.h$", r"^sys/auxv\.h$", r"^error\.h$", r"^execinfo\.h$", r"^gnu/.+", r"^features\.h$"],
   sym=[r"\bstrchrnul\b", r"\bmemrchr\b", r"\bqsort_r\b", r"\bsecure_getenv\b", r"\bcanonicalize_file_name\b",
        r"\bget_current_dir_name\b", r"\bargp_parse\b", r"\bobstack_[a-z_]+\b", r"\bprogram_invocation(?:_short)?_name\b",
        r"\bgetauxval\b", r"\bmalloc_trim\b", r"\bbacktrace(?:_symbols(?:_fd)?)?\b", r"\bexplicit_bzero\b",
        r"\bgnu_get_libc_version\b", r"\bfopencookie\b", r"\b__builtin_cpu_[a-z_]+\b"])

_r("QNX021", "non-portable pthread extensions", "process", "medium", "documented",
   "pthread_yield, pthread_tryjoin_np, pthread_timedjoin_np and pthread_getattr_np have no page in the QNX 8.0 "
   "C Library Reference.",
   "pthread_yield() -> sched_yield() (documented). For timed joins, join from a helper thread or use "
   "a condition variable with pthread_cond_timedwait(). pthread_getattr_np: verify. "
   "pthread_setname_np()/pthread_getname_np() exist on QNX 8.0 with the same names.",
   [lib("sched_yield"), lib("pthread_setname_np")],
   sym=[r"\bpthread_yield\b", r"\bpthread_(?:try|timed)join_np\b", r"\bpthread_getattr_np\b"])

_r("QNX022", "raw syscall() / SYS_* numbers", "process", "high", "documented",
   "Linux system-call numbers do not exist on QNX; syscall() has no page in the QNX 8.0 C Library Reference.",
   "Call the libc/QNX API instead. syscall(SYS_gettid) -> gettid() (documented, <process.h>). Others: find the "
   "libc function, or QNX kernel call, that provides the feature.",
   [lib("gettid")],
   inc=[r"^sys/syscall\.h$", r"^asm/unistd.*\.h$"],
   sym=[r"\bsyscall\s*\(", r"\bSYS_[a-z_0-9]{3,}\b", r"\b__NR_[a-z_0-9]+\b"],
   notes=[(r"SYS_gettid", "Direct mapping: gettid() from <process.h>.")])

_r("QNX023", "accept4 / dup3 / SOCK_* creation flags", "io", "medium", "verify",
   "accept4 and dup3 have no page in the QNX 8.0 C Library Reference; SOCK_NONBLOCK/SOCK_CLOEXEC support depends on the "
   "network stack headers of your SDP.",
   "Use accept()/dup2()/socket() followed by fcntl(fd, F_SETFD, FD_CLOEXEC) and fcntl(fd, F_SETFL, O_NONBLOCK) "
   "(a small wrapper keeps the call sites clean). Note the non-atomic window if you fork concurrently (verify). "
   "pipe2() and mkostemp() are documented and can stay.",
   [lib("pipe", "pipe(), pipe2()"), lib("mkostemp")],
   sym=[r"\baccept4\b", r"\bdup3\b", r"\bSOCK_(?:NONBLOCK|CLOEXEC)\b", r"\bpaccept\b"])

_r("QNX024", "Linux file-sync and allocation extensions", "io", "medium", "documented",
   "fallocate, sync_file_range, syncfs and readahead have no page in the QNX 8.0 C Library Reference.",
   "fallocate() -> posix_fallocate() (documented); sync_file_range()/syncfs() -> fdatasync()/fsync()/sync() "
   "(documented where listed in the C Library Reference); readahead() -> posix_fadvise() (documented) or drop.",
   [lib("posix_fallocate"), lib("fdatasync"), lib("posix_fadvise")],
   sym=[r"\bfallocate(?:64)?\b", r"\bsync_file_range\b", r"\bsyncfs\b", r"\breadahead\b", r"\bFALLOC_FL_[A-Z_]+\b"])

_r("QNX025", "statfs / sys/vfs.h", "io", "medium", "documented",
   "statfs()/fstatfs() and <sys/vfs.h>, <sys/statfs.h> are Linux interfaces (no statfs page in the QNX 8.0 C Library Reference).",
   "Use statvfs()/fstatvfs() (documented, <sys/statvfs.h>); map the fields (f_bsize, f_blocks, f_bavail, ...).",
   [lib("statvfs", "statvfs(), fstatvfs()")],
   inc=[r"^sys/vfs\.h$", r"^sys/statfs\.h$"],
   sym=[r"\bf?statfs(?:64)?\s*\(", r"\bstruct\s+statfs\b"])

_r("QNX026", "Linux-only clock IDs", "time", "medium", "verify",
   "The clock_gettime() page lists CLOCK_REALTIME, CLOCK_MONOTONIC and the CPU-time clocks; CLOCK_BOOTTIME, "
   "CLOCK_MONOTONIC_RAW, *_COARSE and CLOCK_TAI are Linux clocks and are not documented for QNX 8.0.",
   "Use CLOCK_MONOTONIC for intervals and CLOCK_REALTIME for wall time. If you need time-since-boot semantics, "
   "decide what to do while suspended (verify behaviour on your target). timer_create() additionally accepts CLOCK_SOFTTIME.",
   [lib("clock_gettime"), lib("timer_create")],
   sym=[r"\bCLOCK_(?:BOOTTIME|MONOTONIC_RAW|REALTIME_COARSE|MONOTONIC_COARSE|TAI|REALTIME_ALARM|BOOTTIME_ALARM)\b"])

_r("QNX027", "Linux-only mmap/madvise options", "io", "medium", "verify",
   "mmap() on QNX documents MAP_ANON (not MAP_ANONYMOUS), MAP_LAZY, MAP_NORESERVE, MAP_STACK and others; "
   "MAP_POPULATE, MAP_HUGETLB, MAP_GROWSDOWN, MAP_LOCKED, MAP_32BIT and mremap() are Linux features.",
   "Use MAP_ANON, drop prefault/huge-page flags (or find the QNX equivalent in the mmap() page), and replace "
   "mremap() with mmap + copy. madvise() has no C Library Reference page: use posix_madvise() (documented) (verify).",
   [lib("mmap"), lib("posix_madvise")],
   sym=[r"\bMAP_(?:POPULATE|HUGETLB|HUGE_\w+|GROWSDOWN|LOCKED|32BIT|NONBLOCK|DENYWRITE|EXECUTABLE)\b", r"\bmremap\b",
        r"\bMREMAP_[A-Z]+\b", r"\bMAP_ANONYMOUS\b", r"\bmadvise\b", r"\bMADV_[A-Z_]+\b"],
   notes=[(r"MAP_ANONYMOUS", "MAP_ANON is the documented spelling; check if your <sys/mman.h> aliases MAP_ANONYMOUS.")])

_r("QNX028", "Linux-only open() flags", "io", "medium", "verify",
   "O_TMPFILE, O_PATH, O_NOATIME and O_DIRECT are Linux flags; support on QNX filesystems is not documented in the public C library pages searched.",
   "Use a mkstemp()+unlink() sequence for O_TMPFILE, drop O_NOATIME, and decide per filesystem about O_DIRECT. Verify each flag is defined in your SDP <fcntl.h>.",
   [lib("mkostemp")],
   sym=[r"\bO_(?:TMPFILE|PATH|NOATIME|DIRECT)\b"])

_r("QNX029", "Linux capabilities", "security", "high", "documented",
   "<sys/capability.h> and cap_*() (libcap) are Linux capabilities. QNX 8.0 uses process abilities.",
   "Use procmgr_ability() to grant/lock abilities (for example PROCMGR_AID_MEM_PHYS, PROCMGR_AID_SPAWN_SETUID, "
   "PROCMGR_AID_XPROCESS_ABLE, as listed on that page). Decide per capability which ability you need.",
   [lib("procmgr_ability"), lib("procmgr_ability_create")],
   inc=[r"^sys/capability\.h$", r"^linux/capability\.h$"],
   sym=[r"\bcap_(?:get_proc|set_proc|set_flag|init|free|from_text|to_text)\b", r"\bCAP_(?:NET_BIND_SERVICE|SYS_ADMIN|SYS_NICE|NET_ADMIN|SYS_RAWIO|DAC_OVERRIDE|SETUID|SETGID|CHOWN)\b"])

_r("QNX030", "containers, namespaces and seccomp", "security", "high", "verify",
   "clone(CLONE_NEW*), unshare(), setns(), seccomp and cgroups (/sys/fs/cgroup) are Linux kernel features.",
   "There is no one-to-one mapping. Isolation on QNX is built from process abilities, the security policy and "
   "separate process managers/partitions: design the equivalent and verify against the QNX System Security Guide.",
   [lib("procmgr_ability")],
   inc=[r"^sys/seccomp\.h$", r"^linux/seccomp\.h$", r"^seccomp\.h$"],
   sym=[r"\bunshare\b", r"\bsetns\b", r"\bCLONE_NEW[A-Z]+\b", r"\bseccomp(?:_init|_rule_add|_load)?\b", r"\bSECCOMP_[A-Z_]+\b",
        r"\bclone\s*\(", r"\bpivot_root\b"],
   string=[r"^/sys/fs/cgroup"])

_r("QNX031", "ptrace", "security", "high", "verify",
   "ptrace and <sys/ptrace.h> have no page in the QNX 8.0 C Library Reference.",
   "QNX debugging/inspection goes through the /proc interface (devctl() DCMD_PROC_* commands) described in the "
   "Programmer's Guide; PTRACE_* requests must be mapped individually (verify).",
   [DOC_PROC, lib("devctl")],
   inc=[r"^sys/ptrace\.h$"],
   sym=[r"\bptrace\s*\(", r"\bPTRACE_[A-Z_]+\b"])

_r("QNX032", "Linux scheduling policies and RT priority ranges", "process", "low", "documented",
   "SCHED_BATCH, SCHED_IDLE and SCHED_DEADLINE are Linux policies. Fixed priority numbers chosen for Linux's SCHED_FIFO/SCHED_RR "
   "range (1-99) do not carry over to QNX's priority scheme.",
   "Query the range at run time with sched_get_priority_min()/sched_get_priority_max() and choose priorities "
   "explicitly for the QNX system design; sched_setscheduler(), pthread_setschedparam() and pthread_setschedprio() are documented.",
   [lib("sched_get_priority_max", "sched_get_priority_min(), sched_get_priority_max()"),
    lib("sched_setscheduler"), lib("pthread_setschedparam")],
   sym=[r"\bSCHED_(?:BATCH|IDLE|DEADLINE)\b", r"\bsched_setattr\b", r"\bSCHED_RESET_ON_FORK\b"])

_r("QNX033", "SIGEV_THREAD_ID", "events", "medium", "documented",
   "SIGEV_THREAD_ID / sigev_notify_thread_id are Linux extensions; the QNX sigevent page lists SIGEV_SIGNAL_THREAD instead.",
   "Use SIGEV_SIGNAL_THREAD (a QNX event type that signals a specific thread; which thread depends on the context, read the sigevent page) or SIGEV_PULSE.",
   [lib("sigevent", "sigevent")],
   sym=[r"\bSIGEV_THREAD_ID\b", r"\bsigev_notify_thread_id\b", r"\b_sigev_un\._tid\b"])

_r("QNX034", "Linux socket options and netlink", "network", "medium", "verify",
   "TCP_CORK, TCP_QUICKACK, TCP_USER_TIMEOUT, SO_BINDTODEVICE, MSG_MORE, AF_PACKET and AF_NETLINK are Linux networking features; "
   "the QNX networking stack is documented separately from the C Library Reference.",
   "Check each option in the QNX 8.0 networking documentation / your SDP <netinet/tcp.h>; BSD-style alternatives "
   "(for example TCP_NOPUSH for corking, routing sockets instead of netlink) are likely but must be verified.",
   [],
   sym=[r"\bTCP_(?:CORK|QUICKACK|USER_TIMEOUT|DEFER_ACCEPT|FASTOPEN|CONGESTION|THIN_LINEAR_TIMEOUTS)\b", r"\bSO_BINDTODEVICE\b",
        r"\bMSG_(?:MORE|ZEROCOPY|CMSG_CLOEXEC)\b", r"\bAF_(?:NETLINK|PACKET)\b", r"\bNETLINK_[A-Z_]+\b", r"\bSO_REUSEPORT_LB\b"],
   inc=[r"^linux/netlink\.h$", r"^linux/rtnetlink\.h$", r"^netpacket/packet\.h$", r"^net/ethernet\.h$"])

_r("QNX035", "systemd / udev integration", "system", "high", "verify",
   "<systemd/...> and <libudev.h> are Linux service/device-manager libraries.",
   "Replace service notification and device hotplug with the QNX equivalents for your system: process start-up "
   "via your boot scripts or system launch manager, procmgr_daemon() for daemonizing (documented) and QNX device "
   "managers. Make the dependency optional (verify design).",
   [lib("procmgr_daemon")],
   inc=[r"^systemd/.+", r"^libudev\.h$", r"^dbus/.+"],
   sym=[r"\bsd_(?:notify|listen_fds|journal_[a-z_]+)\b", r"\budev_[a-z_]+\b"])

_r("QNX036", "ALSA audio", "io", "medium", "verify",
   "<alsa/asoundlib.h> is the Linux ALSA API.",
   "QNX provides its own audio stack (QNX Sound Architecture) with an ALSA-like snd_pcm API; coverage differs "
   "from Linux ALSA, so check each call you use in the QNX audio documentation (verify).",
   [],
   inc=[r"^alsa/.+"])

_r("QNX037", "peer credentials on sockets", "security", "medium", "verify",
   "SO_PEERCRED, struct ucred and SCM_CREDENTIALS are Linux socket features.",
   "For native QNX IPC the server obtains the client identity with iofunc_client_info_ext() in a resource manager. For "
   "UNIX-domain sockets check what your network stack documents (verify).",
   [lib("iofunc_client_info_ext")],
   sym=[r"\bSO_PEERCRED\b", r"\bstruct\s+ucred\b", r"\bSCM_CREDENTIALS\b"])

# --------------------------------------------------------------------------
# Build-system constructs
# --------------------------------------------------------------------------
_r("QNX101", "Linux link flags (-lrt -ldl -lpthread)", "build", "low", "verify",
   "The QNX 8.0 pages for pthread_create(), dlopen() and timer_create() list libc as the library "
   "(\"usually included automatically\"); separate librt/libdl/libpthread are normally not needed.",
   "Drop the flags on QNX, or make them conditional so a missing library does not break the link (verify "
   "which stub libraries your SDP ships).",
   [lib("pthread_create"), lib("dlopen"), lib("timer_create")],
   build=[r"(?:^|[\s'\"=])-l(?:rt|dl|pthread)\b", r"\bfind_library\s*\(\s*\w+\s+(?:rt|dl|pthread)\b",
          r"\bCMAKE_DL_LIBS\b",
          r"\btarget_link_libraries\s*\(.*[\s}](?:rt|dl|pthread)(?=[\s)])"])

_r("QNX102", "host-architecture compiler flags", "build", "medium", "verify",
   "-march=native and -mtune=native optimise for the machine running the compiler; when cross-compiling with qcc "
   "for aarch64le or x86_64 QNX targets they describe the wrong CPU.",
   "Choose explicit target flags (for example -mcpu/-march values for your target board), or none.",
   [DOC_QCC],
   build=[r"-m(?:arch|tune|cpu)=native\b", r"-march=(?:haswell|skylake|znver\d)\b"])

_r("QNX103", "hard-coded host compiler", "build", "medium", "documented",
   "The build calls gcc/g++/cc directly instead of the QNX compiler driver.",
   "Use qcc (C) / q++ (C++) and select the target with -V, for example qcc -Vgcc_ntoaarch64le or "
   "-Vgcc_ntox86_64. Generate a starter with: qnxport scaffold.",
   [DOC_QCC],
   build=[r"^\s*(?:CC|CXX)\s*[:?]?=\s*(?:g\+\+|gcc|cc|clang\+\+|clang)\b",
          r"\bset\s*\(\s*CMAKE_(?:C|CXX)_COMPILER\s+\"?(?:g\+\+|gcc|cc|clang\+\+|clang)\"?\s*\)"])

_r("QNX104", "OS detection that only knows Linux", "build", "medium", "verify",
   "uname -s / CMAKE_SYSTEM_NAME / configure host checks branch on Linux; on a QNX cross build none of the Linux branches "
   "apply, and there may be no branch for QNX at all.",
   "Add a QNX branch (CMake with a QNX toolchain reports CMAKE_SYSTEM_NAME = QNX; autoconf host triplets contain 'nto-qnx'): "
   "verify with your toolchain and your config.sub version.",
   [DOC_QCC],
   build=[r"\$\(\s*shell\s+uname\b", r"`uname\s+-s`", r"\$\(uname\s+-s\)", r"CMAKE_SYSTEM_NAME\s+(?:STREQUAL|MATCHES|EQUAL)\s+\"?Linux",
          r"\bif\s*\(\s*UNIX\s+AND\s+NOT\s+APPLE\s*\)", r"\bAC_CANONICAL_HOST\b", r"\bhost_os\b", r"\bmeson\.get_compiler.*linux",
          r"\bhost_machine\.system\(\)\s*==\s*'linux'"])

_r("QNX105", "sanitizers and Linux-only linker flags", "build", "low", "verify",
   "-fsanitize=*, -Wl,--no-undefined and -Wl,-z,* are common on Linux builds; whether your QNX SDP's compiler/linker accepts them is not stated in the pages searched.",
   "Make them conditional for the QNX target and test the link with your SDP (verify).",
   [DOC_QCC],
   build=[r"-fsanitize=", r"-Wl,--no-undefined", r"-Wl,-z,(?:relro|now|noexecstack)", r"-Wl,--as-needed", r"-Wl,--gc-sections\b"])

RULE_BY_ID = {r.id: r for r in RULES}

# Extra project-level advice produced by the scanner (not pattern rules).
ADVICE = {
    "QNX150": Rule("QNX150", "BSD sockets need -lsocket", "build", "low", "verify",
                   "The code includes socket headers, but no build file in the scanned tree links -lsocket.",
                   "On QNX the socket API is normally provided by libsocket: add -lsocket to the link line (verify against the "
                   "networking documentation for your SDP).",
                   [DOC_QCC]),
    "QNX151": Rule("QNX151", "inotify needs -lfsnotify", "build", "medium", "documented",
                   "The code uses inotify but no build file links fsnotify.",
                   "Add -lfsnotify to the link line (documented on the inotify_init() page) and ensure fsevmgr runs on the target.",
                   [lib("inotify_init", "inotify_init(), inotify_init1()")]),
}
for _a in ADVICE.values():
    RULE_BY_ID[_a.id] = _a

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
SARIF_LEVEL = {"high": "error", "medium": "warning", "low": "note", "info": "note"}
