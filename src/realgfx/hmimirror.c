/*
 * hmimirror - guest helper of IDEmu's "real_graphics" environments (docs/REAL_GRAPHICS.md).
 *
 * IDEmu draws the HMI on the host (glhost), outside the guest's real QNX Screen server. This program gives the HMI a
 * real Screen window with the id string "256", the id LayerManagerService binds to the HMI's surface 256 on the car,
 * so the real scene (screen 0 -> layer 0x80000000 -> surface 256) can be set up. The host (idemu/hmimirror_host.py)
 * copies IDEmu's HMI frame into the window's buffer through the file-backed guest RAM; this program writes where that
 * buffer lies in physical memory to /var/hmimirror.map:
 *     hmimirror 1 <width> <height> <stride> <bytes>
 *     <offset in buffer> <physical address> <length>      (one line per physically contiguous run, hex)
 *     ctl <physical address>                               (control page, hex; absent if it could not be allocated)
 * and posts the window whenever the host bumps the counter in the control page, plus once a second as a keepalive.
 *
 * Usage: hmimirror [id-string [width height]]        (defaults: 256 1440 540)
 * Environment: HMIMIRROR_SCREEN_LIB (the real libscreen.so.1; IDEmu's shim takes /lib/libscreen.so.1),
 *              HMIMIRROR_POLL_MS (15), HMIMIRROR_PERIOD_MS (1000).
 * libscreen is loaded with dlopen, so no QNX Screen headers or import library are needed to build it: see build.sh.
 */
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

/* Numeric values of the QNX Screen constants SCREEN_PROPERTY_FORMAT, _ID_STRING, _POINTER, _POSITION, _RENDER_BUFFERS, _SIZE,
 * _STRIDE, _USAGE, SCREEN_USAGE_NATIVE, _WRITE and SCREEN_FORMAT_RGBA8888, written out because the toolchain build.sh uses has no
 * <screen/screen.h>. Checked in IDEmu against the firmware's libscreen.so.1: LayerManagerService finds the window by its id,
 * it has the requested size, and the stride read back is width * 4. */
enum { P_FORMAT = 14, P_ID_STRING = 20, P_POINTER = 34, P_POSITION = 35, P_RENDER_BUFFERS = 37, P_SIZE = 40,
       P_STRIDE = 44, P_USAGE = 48 };
enum { USAGE_NATIVE = 1, USAGE_WRITE = 4, FORMAT_RGBA8888 = 8 };

typedef void *scr_ctx, *scr_win, *scr_buf;
static struct {
    void *lib;
    int (*create_context)(scr_ctx *, int);
    int (*create_window_type)(scr_win *, scr_ctx, int);
    int (*destroy_window)(scr_win);
    int (*set_window_iv)(scr_win, int, const int *);
    int (*set_window_cv)(scr_win, int, int, const char *);
    int (*get_window_pv)(scr_win, int, void **);
    int (*create_window_buffers)(scr_win, int);
    int (*get_buffer_iv)(scr_buf, int, int *);
    int (*get_buffer_pv)(scr_buf, int, void **);
    int (*post_window)(scr_win, scr_buf, int, const int *, int);
} S;

static volatile sig_atomic_t stop;
static void on_signal(int sig) { (void)sig; stop = 1; }

static int load(const char *name)
{
    S.lib = dlopen(name, RTLD_NOW);
    if (!S.lib) { fprintf(stderr, "hmimirror: cannot load %s (%s)\n", name, dlerror()); return -1; }
#define SYM(f, s) do { void *p_ = dlsym(S.lib, s); if (!p_) { fprintf(stderr, "hmimirror: no %s\n", s); return -1; } \
                       memcpy(&S.f, &p_, sizeof p_); } while (0)
    SYM(create_context, "screen_create_context");
    SYM(create_window_type, "screen_create_window_type");
    SYM(destroy_window, "screen_destroy_window");
    SYM(set_window_iv, "screen_set_window_property_iv");
    SYM(set_window_cv, "screen_set_window_property_cv");
    SYM(get_window_pv, "screen_get_window_property_pv");
    SYM(create_window_buffers, "screen_create_window_buffers");
    SYM(get_buffer_iv, "screen_get_buffer_property_iv");
    SYM(get_buffer_pv, "screen_get_buffer_property_pv");
    SYM(post_window, "screen_post_window");
#undef SYM
    return 0;
}

int main(int argc, char **argv)
{
    const char *lib = getenv("HMIMIRROR_SCREEN_LIB");
    const char *idstr = argc > 1 ? argv[1] : "256";
    int w = argc > 3 ? atoi(argv[2]) : 1440, h = argc > 3 ? atoi(argv[3]) : 540;
    const char *mapfile = "/var/hmimirror.map";      /* /var is a qnx4 RAM disk here: rename works, unlike /dev/shmem */
    int period_ms = getenv("HMIMIRROR_PERIOD_MS") ? atoi(getenv("HMIMIRROR_PERIOD_MS")) : 1000;
    int poll_ms = getenv("HMIMIRROR_POLL_MS") ? atoi(getenv("HMIMIRROR_POLL_MS")) : 15;
    scr_ctx ctx; scr_win win; scr_buf buf[1]; void *ptr = NULL;
    int usage = USAGE_NATIVE | USAGE_WRITE, format = FORMAT_RGBA8888, size[2], pos[2] = {0, 0}, rect[4], stride = 0;
    size_t bytes, done = 0;
    volatile uint32_t *ctl;
    off64_t coff = 0;
    size_t ccontig = 0;
    uint32_t last = 0;
    long since = 0;
    FILE *m;
    char tmp[64];

    if (w < 64 || h < 64 || w > 4096 || h > 4096) { fprintf(stderr, "hmimirror: bad size %dx%d\n", w, h); return 1; }
    size[0] = w; size[1] = h;
    rect[0] = 0; rect[1] = 0; rect[2] = w; rect[3] = h;
    if (load(lib ? lib : "/fs/sda0/repository/istep/lib/libscreen.so.1") != 0) return 1;
    if (S.create_context(&ctx, 0) != 0 || S.create_window_type(&win, ctx, 0) != 0) {
        fprintf(stderr, "hmimirror: screen context/window failed (errno %d)\n", errno); return 2;
    }
    S.set_window_cv(win, P_ID_STRING, (int)strlen(idstr), idstr);
    S.set_window_iv(win, P_USAGE, &usage);
    S.set_window_iv(win, P_FORMAT, &format);
    S.set_window_iv(win, P_SIZE, size);
    S.set_window_iv(win, P_POSITION, pos);
    if (S.create_window_buffers(win, 1) != 0 || S.get_window_pv(win, P_RENDER_BUFFERS, (void **)buf) != 0 || !buf[0] ||
        S.get_buffer_pv(buf[0], P_POINTER, &ptr) != 0 || !ptr) {
        fprintf(stderr, "hmimirror: window buffer failed (errno %d)\n", errno); return 3;
    }
    if (S.get_buffer_iv(buf[0], P_STRIDE, &stride) != 0 || stride < w * 4 || stride > w * 8) {
        fprintf(stderr, "hmimirror: no usable stride (%d); assuming %d\n", stride, w * 4);
        stride = w * 4;
    }
    bytes = (size_t)stride * h;
    {   /* dark grey until the host's first frame arrives */
        int x, y;
        for (y = 0; y < h; y++)
            for (x = 0; x < w; x++) ((uint32_t *)((char *)ptr + (size_t)y * stride))[x] = 0xff202428u;
    }
    snprintf(tmp, sizeof tmp, "%s.tmp", mapfile);
    if (!(m = fopen(tmp, "w"))) { fprintf(stderr, "hmimirror: cannot write %s\n", tmp); return 4; }
    fprintf(m, "hmimirror 1 %d %d %d %lx\n", w, h, stride, (unsigned long)bytes);
    while (done < bytes) {
        off64_t off = 0; size_t contig = 0;
        if (mem_offset64((char *)ptr + done, NOFD, bytes - done, &off, &contig) != 0 || contig == 0) {
            fprintf(stderr, "hmimirror: mem_offset64 failed at %lx (errno %d)\n", (unsigned long)done, errno);
            fclose(m); return 5;
        }
        if (contig > bytes - done) contig = bytes - done;
        fprintf(m, "%lx %llx %lx\n", (unsigned long)done, (unsigned long long)off, (unsigned long)contig);
        done += contig;
    }
    /* A physically contiguous control page: the host writes a frame counter at offset 0 after each copy, and the
     * window is posted as soon as it changes (polled every poll_ms), plus once per period_ms as a keepalive. */
    ctl = mmap(0, 4096, PROT_READ | PROT_WRITE | PROT_NOCACHE, MAP_PHYS | MAP_ANON | MAP_SHARED, NOFD, 0);
    if (ctl == MAP_FAILED || mem_offset64((void *)ctl, NOFD, 4096, &coff, &ccontig) != 0) {
        fprintf(stderr, "hmimirror: no control page (errno %d); posting on the timer only\n", errno);
        ctl = NULL;
    } else {
        ctl[0] = 0;
        fprintf(m, "ctl %llx\n", (unsigned long long)coff);
    }
    fclose(m);
    rename(tmp, mapfile);
    signal(SIGTERM, on_signal); signal(SIGINT, on_signal); signal(SIGHUP, SIG_IGN);
    if (poll_ms < 1) poll_ms = 1;
    printf("hmimirror: window \"%s\" %dx%d stride %d; posted on each host frame (poll %d ms), keepalive %d ms; map in %s\n",
           idstr, w, h, stride, poll_ms, period_ms, mapfile);
    fflush(stdout);
    while (!stop) {
        struct timespec ts = { poll_ms / 1000, (long)(poll_ms % 1000) * 1000000L };
        uint32_t now = ctl ? ctl[0] : 0;
        since += poll_ms;
        if ((ctl && now != last) || since >= period_ms) {
            S.post_window(win, buf[0], 1, rect, 0);
            last = now; since = 0;
        }
        nanosleep(&ts, NULL);
    }
    S.destroy_window(win);
    unlink(mapfile);
    return 0;
}
