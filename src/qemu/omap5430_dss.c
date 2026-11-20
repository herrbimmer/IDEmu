/*
 * Minimal OMAP5430 DSS/DMM model for BMW NBTevo.
 *
 * The register windows provide read-after-write behavior for the QNX WFD
 * driver. The DSS display callback scans out linear guest RAM using the
 * DISPC overlay registers. This is a software display path; it does not
 * emulate SGX540 or Vivante command processors.
 *
 * Origin: hw/display/omap5430_dss.c of agent00jackson/bimmulator
 * (https://github.com/agent00jackson/bimmulator), commit bf03f2e,
 * nix/patches/qemu/0001-omap5-core.patch.
 * IDEmu additions: the IDEMU_DSS_FRAME scan-out to a frame file (two
 * includes, the dump_* fields, omap5430_dump_frame/omap5430_dump_init and
 * one call in realize). No line of the original was removed or changed.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "hw/display/omap5430_dss.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "qemu/module.h"
#include "migration/vmstate.h"
#include "qemu/log.h"
#include "qemu/timer.h"
#include "system/memory.h"
#include "ui/console.h"
#include "ui/pixel_ops.h"
#include <sys/mman.h>
#include <fcntl.h>

#define OMAP5430_DSS_BASE             0x58000000
#define OMAP5430_DSS_SIZE             0x00080000
#define OMAP5430_DMM_BASE             0x4e000000
#define OMAP5430_DMM_SIZE             0x00001000
#define OMAP5430_CM_CORE_BASE       0x4a008000
#define OMAP5430_CM_CORE_SIZE       0x00002000
#define OMAP5430_HDMI_W1_BASE         0x4a002800
#define OMAP5430_HDMI_W1_SIZE         0x00000800
#define HDMI_WP_SYSCONFIG             0x0010
#define HDMI_WP_SYSS                  0x0014
#define HDMI_WP_SYSCONFIG_SOFTRESET   (1U << 1)
#define HDMI_WP_SYSS_RESETDONE        (1U << 0)
#define OMAP5430_HDMI_CTRL_BASE       0x4a100000
#define OMAP5430_HDMI_CTRL_SIZE       0x00003000
#define OMAP5430_CTRL_BASE            0x48050000
#define OMAP5430_CTRL_SIZE            0x00001000
#define OMAP5430_PAD_BASE             0x48058000
#define OMAP5430_PAD_SIZE             0x00002000
#define OMAP5430_DSS_ALT0_BASE        0x4a307100
#define OMAP5430_DSS_ALT1_BASE        0x4ae07100
#define OMAP5430_DSS_ALT_SIZE         0x00000040

#define DSS_DISPC_BASE                0x1000
#define DISPC_IRQSTATUS               0x0018
#define DISPC_IRQENABLE               0x001c
#define DISPC_CONTROL                 0x0040
#define DISPC_ENABLE_LCD              (1U << 0)
#define DISPC_ENABLE_DIGITAL          (1U << 1)
#define DISPC_GO_LCD                  (1U << 5)
#define DISPC_GO_DIGITAL              (1U << 6)
#define DISPC_IRQ_VSYNC               (1U << 1)
#define DISPC_IRQ_EVSYNC_EVEN         (1U << 2)
#define DISPC_IRQ_EVSYNC_ODD          (1U << 3)
#define DISPC_FRAME_NS                16666667
#define DISPC_SIZE_LCD                0x007c
#define DISPC_SIZE_LCD2               0x03cc
#define DISPC_SIZE_LCD3               0x0834
#define DISPC_OVL_BA0                 0x0000
#define DISPC_OVL_POS                 0x0008
#define DISPC_OVL_SIZE                0x000c
#define DISPC_OVL_ATTR                0x0010
#define DISPC_OVL_ROW_INC             0x002c
#define DISPC_OVL_PIX_INC             0x0030
#define DISPC_ATTR_ENABLE             0x00000001
#define DISPC_ATTR_FORMAT_SHIFT       1
#define DMM_PAT_HWINFO                0x0408
#define DMM_PAT_GEOMETRY              0x040c
#define DMM_PAT_IRQSTATUS             0x0490
#define DMM_PAT_IRQENABLE_SET         0x04a0
#define DMM_PAT_IRQENABLE_CLR         0x04b0
#define DMM_PAT_STATUS0               0x04c0
#define DMM_PAT_DESCR0                0x0500
#define DMM_PAT_CTRL0                 0x0508
#define DMM_PAT_READY                 0x00000001
#define DMM_PAT_COMPLETE              0x0000000b
#define DMM_PAT_IRQ_LAST               0x02
#define DMM_PAT_IRQ_MANUAL             0x03

#define OMAP5430_WINDOW_COUNT 9
#define OMAP5430_MAX_DIMENSION 4096

typedef struct OMAP5430Window {
    MemoryRegion iomem;
    OMAP5430DSSState *dss;
    uint32_t *regs;
    uint32_t reg_count;
    hwaddr base;
    hwaddr size;
    const char *name;
} OMAP5430Window;

struct OMAP5430DSSState {
    SysBusDevice parent_obj;
    OMAP5430Window windows[OMAP5430_WINDOW_COUNT];
    MemoryRegion *sysmem;
    QemuConsole *con;
    qemu_irq dmm_irq;
    qemu_irq dispc_irq;
    QEMUTimer *frame_timer;
    bool digital_odd;
    hwaddr fb_base;
    hwaddr fb_bytes;
    uint32_t width;
    uint32_t height;
    uint32_t format;
    uint32_t xpos;
    uint32_t ypos;
    bool trace_dmm;
    int invalidate;
    /* IDEmu: IDEMU_DSS_FRAME=<file> writes the scanned-out GFX plane there in IDEmu's frame format
     * ('IDFR', seq, w, h, busy, pad to 32 bytes, then RGB) on a host-clock timer, without a display backend */
    QEMUTimer *dump_timer;
    uint8_t *dump_map, *dump_rgb;
    size_t dump_size;
    uint32_t dump_seq, dump_w, dump_h;
    int dump_ms;
};

static const struct {
    hwaddr base;
    hwaddr size;
    const char *name;
} omap5430_windows[OMAP5430_WINDOW_COUNT] = {
    { OMAP5430_DSS_BASE, OMAP5430_DSS_SIZE, "omap5430-dss" },
    { OMAP5430_DMM_BASE, OMAP5430_DMM_SIZE, "omap5430-dmm" },
    { OMAP5430_CM_CORE_BASE, OMAP5430_CM_CORE_SIZE, "omap5430-cm-core" },
    { OMAP5430_HDMI_W1_BASE, OMAP5430_HDMI_W1_SIZE, "omap5430-hdmi-w1" },
    { OMAP5430_HDMI_CTRL_BASE, OMAP5430_HDMI_CTRL_SIZE, "omap5430-hdmi-ctrl" },
    { OMAP5430_CTRL_BASE, OMAP5430_CTRL_SIZE, "omap5430-control" },
    { OMAP5430_PAD_BASE, OMAP5430_PAD_SIZE, "omap5430-pad" },
    { OMAP5430_DSS_ALT0_BASE, OMAP5430_DSS_ALT_SIZE, "omap5430-dss-alt0" },
    { OMAP5430_DSS_ALT1_BASE, OMAP5430_DSS_ALT_SIZE, "omap5430-dss-alt1" },
};

static uint32_t omap5430_reg_read(OMAP5430Window *w, hwaddr offset)
{
    if (w->base == OMAP5430_DSS_BASE) {
        if (offset == 0x0000) {
            return 0x00000050; /* DSS revision */
        }
        if (offset == DSS_DISPC_BASE) {
            return 0x00000040; /* DISPC revision */
        }
        if (offset == 0x0014 || offset == DSS_DISPC_BASE + 0x0014) {
            return 1; /* reset completed */
        }
    }
    if (w->base == OMAP5430_CM_CORE_BASE) {
        /* CM_GPU: module enable drives the interface/functional clock activity.
         * Bits 10:8 are read-only; the PowerVR driver waits for all three.
         */
        bool enabled = (w->regs[0x1520 / 4] & 3) == 2;
        if (offset == 0x1500) { /* CM_GPU_CLKSTCTRL */
            return (w->regs[offset / 4] & 3) | (enabled ? 0x700 : 0);
        }
        if (offset == 0x1520) { /* CM_GPU_GPU_CLKCTRL */
            return (w->regs[offset / 4] & ~(3U << 16)) |
                   (enabled ? 0 : 3U << 16);
        }
    }
    if (w->base == OMAP5430_DMM_BASE) {
        switch (offset) {
        case 0x0000: /* DMM_REVISION */
            return 0x00000020;
        case 0x0004: /* DMM_HWINFO */
            return 0x00000101;
        case 0x0208: /* DMM_TILER_HWINFO */
            return 0x00000100;
        case DMM_PAT_HWINFO: /* four refill engines, one 2D LUT */
            return 0x04010000;
        case DMM_PAT_GEOMETRY: /* 256 columns by 256 rows */
            return 0x08080000;
        case DMM_PAT_STATUS0:
        case DMM_PAT_STATUS0 + 4:
        case DMM_PAT_STATUS0 + 8:
        case DMM_PAT_STATUS0 + 12:
            return w->regs[offset >> 2] ?: DMM_PAT_READY;
        default:
            break;
        }
    }
    return w->regs[offset >> 2];
}

static uint64_t omap5430_mmio_read(void *opaque, hwaddr offset, unsigned size)
{
    OMAP5430Window *w = opaque;
    uint32_t value = omap5430_reg_read(w, offset & ~3ULL);
    unsigned shift = (offset & 3) * 8;

    if (size == 1) {
        value = (value >> shift) & 0xff;
    } else if (size == 2) {
        value = (value >> shift) & 0xffff;
    }
    if (w->base == OMAP5430_DMM_BASE && w->dss->trace_dmm) {
        qemu_log_mask(LOG_UNIMP, "omap5430-dmm: read%u offset=0x%04x value=0x%08x\n",
                      size, (unsigned)offset, value);
    }
    return value;
}

/* Approximate 60 Hz display timing; register updates latch on a frame. */
static void omap5430_frame(void *opaque)
{
    OMAP5430DSSState *s = opaque;
    OMAP5430Window *w = &s->windows[0];
    uint32_t *control = &w->regs[(DSS_DISPC_BASE + DISPC_CONTROL) / 4];
    uint32_t *status = &w->regs[(DSS_DISPC_BASE + DISPC_IRQSTATUS) / 4];
    uint32_t enable = w->regs[(DSS_DISPC_BASE + DISPC_IRQENABLE) / 4];

    if (*control & DISPC_ENABLE_LCD) {
        *control &= ~DISPC_GO_LCD;
        *status |= DISPC_IRQ_VSYNC;
    }
    if (*control & DISPC_ENABLE_DIGITAL) {
        *control &= ~DISPC_GO_DIGITAL;
        *status |= s->digital_odd ? DISPC_IRQ_EVSYNC_ODD : DISPC_IRQ_EVSYNC_EVEN;
        s->digital_odd = !s->digital_odd;
    }
    qemu_set_irq(s->dispc_irq, (*status & enable) != 0);
    if (*control & (DISPC_ENABLE_LCD | DISPC_ENABLE_DIGITAL)) {
        timer_mod(s->frame_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + DISPC_FRAME_NS);
    }
}

static void omap5430_mmio_write(void *opaque, hwaddr offset,
                                uint64_t value, unsigned size)
{
    OMAP5430Window *w = opaque;
    uint32_t *reg = &w->regs[(offset & ~3ULL) >> 2];
    uint32_t old = *reg;
    uint32_t mask = size == 4 ? UINT32_MAX : ((1U << (size * 8)) - 1);
    unsigned shift = (offset & 3) * 8;
    OMAP5430DSSState *s = w->dss;

    if (w->base == OMAP5430_DMM_BASE && s->trace_dmm) {
        qemu_log_mask(LOG_UNIMP, "omap5430-dmm: write%u offset=0x%04x value=0x%08x\n",
                      size, (unsigned)offset, (unsigned)value);
    }
    *reg = (*reg & ~(mask << shift)) | (((uint32_t)value & mask) << shift);
    if (w->base == OMAP5430_DSS_BASE) {
        w->dss->invalidate = 1;
        if (size == 4 && offset == DSS_DISPC_BASE + DISPC_IRQSTATUS) {
            *reg = old & ~(uint32_t)value;
        }
        if (size == 4 && (offset == DSS_DISPC_BASE + DISPC_IRQSTATUS ||
                          offset == DSS_DISPC_BASE + DISPC_IRQENABLE)) {
            uint32_t status = w->regs[(DSS_DISPC_BASE + DISPC_IRQSTATUS) / 4];
            uint32_t enable = w->regs[(DSS_DISPC_BASE + DISPC_IRQENABLE) / 4];
            qemu_set_irq(s->dispc_irq, (status & enable) != 0);
        } else if (size == 4 && offset == DSS_DISPC_BASE + DISPC_CONTROL) {
            if (value & (DISPC_ENABLE_LCD | DISPC_ENABLE_DIGITAL)) {
                if (!timer_pending(s->frame_timer)) {
                    timer_mod(s->frame_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + DISPC_FRAME_NS);
                }
            } else {
                timer_del(s->frame_timer);
            }
        }
    } else if (w->base == OMAP5430_DMM_BASE && size == 4 && !(offset & 3)) {
        uint32_t *irq_status = &w->regs[DMM_PAT_IRQSTATUS >> 2];
        uint32_t *irq_enable = &w->regs[DMM_PAT_IRQENABLE_SET >> 2];
        uint32_t written = value;

        if (offset == DMM_PAT_IRQENABLE_SET) {
            *irq_enable = old | written;
        } else if (offset == DMM_PAT_IRQENABLE_CLR) {
            *irq_enable &= ~written;
            w->regs[offset >> 2] = written;
        } else if (offset == DMM_PAT_IRQSTATUS) {
            *irq_status = old & ~written;
            w->regs[0x0480 >> 2] &= ~written;
        } else if (offset >= DMM_PAT_CTRL0 && offset <= DMM_PAT_CTRL0 + 0x30 &&
                   !((offset - DMM_PAT_CTRL0) & 0x0f) && (written & 1)) {
            unsigned engine = (offset - DMM_PAT_CTRL0) >> 4;

            /* Bring-up only: completion status, not TILER address translation. */
            w->regs[(DMM_PAT_STATUS0 + engine * 4) >> 2] = DMM_PAT_COMPLETE;
            *irq_status |= DMM_PAT_IRQ_MANUAL << (engine * 8);
            w->regs[0x0480 >> 2] |= DMM_PAT_IRQ_MANUAL << (engine * 8);
        } else if (offset >= DMM_PAT_DESCR0 && offset <= DMM_PAT_DESCR0 + 0x30 &&
                   !((offset - DMM_PAT_DESCR0) & 0x0f)) {
            unsigned engine = (offset - DMM_PAT_DESCR0) >> 4;
            uint32_t *status = &w->regs[(DMM_PAT_STATUS0 + engine * 4) >> 2];

            if (written) {
                *status = DMM_PAT_COMPLETE;
                *irq_status |= DMM_PAT_IRQ_LAST << (engine * 8);
                w->regs[0x0480 >> 2] = *irq_status;
            } else {
                *status = DMM_PAT_READY;
            }
        }
        qemu_set_irq(s->dmm_irq, (*irq_status & *irq_enable) != 0);
    }
}

static const MemoryRegionOps omap5430_mmio_ops = {
    .read = omap5430_mmio_read,
    .write = omap5430_mmio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = {
        .min_access_size = 1,
        .max_access_size = 4,
        .unaligned = true,
    },
    .impl = {
        .min_access_size = 1,
        .max_access_size = 4,
        .unaligned = true,
    },
};

static uint32_t omap5430_reg(const OMAP5430DSSState *s, hwaddr offset)
{
    return omap5430_reg_read((OMAP5430Window *)&s->windows[0], offset);
}

static void omap5430_draw_pixel(uint8_t *dst, const uint8_t *src,
                                uint32_t format, unsigned out_bpp)
{
    unsigned r, g, b;

    if (format == 6 || format == 4 || format == 15 || format == 16 ||
        format == 17 || format == 18) {
        uint16_t v = lduw_le_p((void *)src);
        if (format == 6) {
            r = ((v >> 11) & 0x1f) * 255 / 31;
            g = ((v >> 5) & 0x3f) * 255 / 63;
            b = (v & 0x1f) * 255 / 31;
        } else {
            r = ((v >> 8) & 0xf) * 17;
            g = ((v >> 4) & 0xf) * 17;
            b = (v & 0xf) * 17;
        }
    } else {
        uint32_t v = ldl_le_p((void *)src);
        if (format == 8 || format == 11 || format == 12) {
            /* RGB24 unpacked / ARGB32: 0xXXRRGGBB. */
            r = (v >> 16) & 0xff;
            g = (v >> 8) & 0xff;
            b = v & 0xff;
        } else { /* RGBA32/RGBX32: 0xRRGGBBxx */
            r = (v >> 24) & 0xff;
            g = (v >> 16) & 0xff;
            b = (v >> 8) & 0xff;
        }
    }

    if (out_bpp == 16) {
        *(uint16_t *)dst = rgb_to_pixel16(r, g, b);
    } else {
        *(uint32_t *)dst = rgb_to_pixel32(r, g, b);
    }
}

static bool omap5430_update_display(void *opaque)
{
    OMAP5430DSSState *s = opaque;
    DisplaySurface *surface = qemu_console_surface(s->con);
    uint32_t out_width, out_height, out_bpp;
    uint32_t planes[] = { 0x0080, 0x00bc, 0x014c, 0x01bc };
    uint8_t *dest;
    bool found = false;
    unsigned i, x, y;

    if (!surface) {
        return true;
    }
    out_bpp = surface_bits_per_pixel(surface);
    if (out_bpp != 16 && out_bpp != 32) {
        return true;
    }

    out_width = (omap5430_reg(s, DSS_DISPC_BASE + DISPC_SIZE_LCD) & 0x7ff) + 1;
    out_height = ((omap5430_reg(s, DSS_DISPC_BASE + DISPC_SIZE_LCD) >> 16) & 0x7ff) + 1;
    if (out_width <= 1 || out_height <= 1) {
        out_width = (omap5430_reg(s, DSS_DISPC_BASE + DISPC_SIZE_LCD2) & 0x7ff) + 1;
        out_height = ((omap5430_reg(s, DSS_DISPC_BASE + DISPC_SIZE_LCD2) >> 16) & 0x7ff) + 1;
    }
    if (out_width <= 1 || out_height <= 1) {
        out_width = (omap5430_reg(s, DSS_DISPC_BASE + DISPC_SIZE_LCD3) & 0x7ff) + 1;
        out_height = ((omap5430_reg(s, DSS_DISPC_BASE + DISPC_SIZE_LCD3) >> 16) & 0x7ff) + 1;
    }
    /*
     * The NBTevo digital Screen path can leave all LCD_SIZE registers at
     * reset while programming the active overlay with the actual mode size.
     * Match the compositor's plane order and derive the output surface from
     * the first enabled, dimensioned plane before using the generic fallback.
     */
    if (out_width <= 1 || out_height <= 1) {
        for (i = 0; i < ARRAY_SIZE(planes); i++) {
            hwaddr p = DSS_DISPC_BASE + planes[i];
            uint32_t attr = omap5430_reg(s, p + (i == 0 ? 0x20 : DISPC_OVL_ATTR));
            uint32_t size = omap5430_reg(s, p + DISPC_OVL_SIZE);
            uint32_t plane_width = (size & 0x7ff) + 1;
            uint32_t plane_height = ((size >> 16) & 0x7ff) + 1;
            if ((attr & DISPC_ATTR_ENABLE) && plane_width >= 64 &&
                plane_height >= 64 && plane_width <= OMAP5430_MAX_DIMENSION &&
                plane_height <= OMAP5430_MAX_DIMENSION) {
                out_width = plane_width;
                out_height = plane_height;
                break;
            }
        }
    }
    if (out_width < 64 || out_width > OMAP5430_MAX_DIMENSION ||
        out_height < 64 || out_height > OMAP5430_MAX_DIMENSION) {
        out_width = 1280;
        out_height = 480;
    }
    if (out_width != surface_width(surface) || out_height != surface_height(surface)) {
        qemu_console_resize(s->con, out_width, out_height);
        surface = qemu_console_surface(s->con);
        s->invalidate = 1;
    }

    dest = surface_data(surface);
    for (i = 0; i < ARRAY_SIZE(planes); i++) {
        hwaddr p = DSS_DISPC_BASE + planes[i];
        /* The GFX plane has a different attributes offset than video. */
        uint32_t attr = omap5430_reg(s, p + (i == 0 ? 0x20 : DISPC_OVL_ATTR));
        uint32_t size = omap5430_reg(s, p + DISPC_OVL_SIZE);
        uint32_t width = (size & 0x7ff) + 1;
        uint32_t height = ((size >> 16) & 0x7ff) + 1;
        uint32_t format = (attr >> DISPC_ATTR_FORMAT_SHIFT) & 0xf;
        uint32_t bpp = (format == 6 || format == 4 || format >= 15) ? 2 : 4;
        int32_t row_inc = (int32_t)omap5430_reg(s, p + DISPC_OVL_ROW_INC);
        int32_t pixel_inc = (int32_t)omap5430_reg(s, p + DISPC_OVL_PIX_INC);
        hwaddr base = omap5430_reg(s, p + DISPC_OVL_BA0);
        uint32_t position = omap5430_reg(s, p + DISPC_OVL_POS);
        uint32_t xpos = position & 0x7ff;
        uint32_t ypos = (position >> 16) & 0x7ff;
        int64_t pixel_step = (int64_t)bpp + pixel_inc - 1;
        int64_t row_step = (int64_t)(width - 1) * pixel_step + bpp + row_inc - 1;
        uint64_t bytes;
        MemoryRegionSection sec;
        uint8_t *src;

        if (!(attr & DISPC_ATTR_ENABLE) || width < 2 || height < 2 ||
            width > OMAP5430_MAX_DIMENSION || height > OMAP5430_MAX_DIMENSION ||
            base == 0 || pixel_step <= 0 || row_step <= 0) {
            continue;
        }
        /* OMAP's increment registers are extra offsets after each pixel/row.
         * Keep only positive linear fetches here; rotated layouts need signed
         * base-address adjustment before they can be scanned out safely. */
        bytes = (uint64_t)(height - 1) * (uint64_t)row_step +
                (uint64_t)(width - 1) * (uint64_t)pixel_step + bpp;
        if (bytes > 128ULL * 1024 * 1024) {
            continue;
        }
        sec = memory_region_find(s->sysmem, base, bytes);
        if (!sec.mr || !memory_region_is_ram(sec.mr) ||
            int128_get64(sec.size) < bytes) {
            if (sec.mr) {
                memory_region_unref(sec.mr);
            }
            continue;
        }
        src = memory_region_get_ram_ptr(sec.mr) + sec.offset_within_region;
        for (y = 0; y < height && y + ypos < out_height; y++) {
            uint8_t *d = dest + (y + ypos) * surface_stride(surface) + xpos * (out_bpp / 8);
            const uint8_t *r = src + (uint64_t)y * (uint64_t)row_step;
            for (x = 0; x < width && x + xpos < out_width; x++) {
                omap5430_draw_pixel(d + x * (out_bpp / 8),
                                    r + (uint64_t)x * (uint64_t)pixel_step,
                                    format, out_bpp);
            }
        }
        memory_region_unref(sec.mr);
        s->fb_base = base;
        s->width = width;
        s->height = height;
        s->format = format;
        found = true;
        s->invalidate = 0;
        break; /* The GFX plane carries the composed iDrive UI. */
    }

    if (!found && s->invalidate) {
        memset(dest, 0, surface_stride(surface) * surface_height(surface));
        s->invalidate = 0;
    }
    if (found || s->invalidate == 0) {
        qemu_console_update(s->con, 0, 0, surface_width(surface), surface_height(surface));
    }
    return true;
}

/* IDEmu: see dump_* in OMAP5430DSSState */
#define DUMP_HDR 32
static void omap5430_dump_frame(void *opaque)
{
    OMAP5430DSSState *s = opaque;
    uint32_t planes[] = { 0x0080, 0x00bc, 0x014c, 0x01bc };
    unsigned i, x, y;

    for (i = 0; i < ARRAY_SIZE(planes); i++) {
        hwaddr p = DSS_DISPC_BASE + planes[i];
        uint32_t attr = omap5430_reg(s, p + (i == 0 ? 0x20 : DISPC_OVL_ATTR));
        uint32_t size = omap5430_reg(s, p + DISPC_OVL_SIZE);
        uint32_t width = (size & 0x7ff) + 1, height = ((size >> 16) & 0x7ff) + 1;
        uint32_t format = (attr >> DISPC_ATTR_FORMAT_SHIFT) & 0xf;
        uint32_t bpp = (format == 6 || format == 4 || format >= 15) ? 2 : 4;
        int32_t row_inc = (int32_t)omap5430_reg(s, p + DISPC_OVL_ROW_INC);
        int32_t pixel_inc = (int32_t)omap5430_reg(s, p + DISPC_OVL_PIX_INC);
        hwaddr base = omap5430_reg(s, p + DISPC_OVL_BA0);
        int64_t pixel_step = (int64_t)bpp + pixel_inc - 1;
        int64_t row_step = (int64_t)(width - 1) * pixel_step + bpp + row_inc - 1;
        uint64_t bytes;
        size_t n;
        MemoryRegionSection sec;
        const uint8_t *src;
        uint8_t *rgb = s->dump_rgb;

        if (!(attr & DISPC_ATTR_ENABLE) || width < 64 || height < 64 || base == 0 || pixel_step <= 0 || row_step <= 0 ||
            (size_t)width * height * 3 + DUMP_HDR > s->dump_size) {
            continue;
        }
        bytes = (uint64_t)(height - 1) * (uint64_t)row_step + (uint64_t)(width - 1) * (uint64_t)pixel_step + bpp;
        sec = memory_region_find(s->sysmem, base, bytes);
        if (!sec.mr || !memory_region_is_ram(sec.mr) || int128_get64(sec.size) < bytes) {
            if (sec.mr) {
                memory_region_unref(sec.mr);
            }
            continue;
        }
        src = memory_region_get_ram_ptr(sec.mr) + sec.offset_within_region;
        for (y = 0; y < height; y++) {
            const uint8_t *r = src + (uint64_t)y * (uint64_t)row_step;
            for (x = 0; x < width; x++) {
                uint32_t px = 0;
                omap5430_draw_pixel((uint8_t *)&px, r + (uint64_t)x * (uint64_t)pixel_step, format, 32);
                *rgb++ = (px >> 16) & 0xff; *rgb++ = (px >> 8) & 0xff; *rgb++ = px & 0xff;
            }
        }
        memory_region_unref(sec.mr);
        n = (size_t)width * height * 3;
        if (width != s->dump_w || height != s->dump_h || memcmp(s->dump_map + DUMP_HDR, s->dump_rgb, n) != 0) {
            uint32_t *h = (uint32_t *)s->dump_map;
            uint32_t next = s->dump_seq + 1 ? s->dump_seq + 1 : 1;
            h[4] = next;                                   /* busy: frame being written */
            memcpy(s->dump_map + DUMP_HDR, s->dump_rgb, n);
            h[2] = width; h[3] = height; h[0] = 0x52464449; /* 'IDFR' */
            h[1] = next;                                   /* seq == busy: complete */
            s->dump_seq = next; s->dump_w = width; s->dump_h = height;
        }
        break;
    }
    timer_mod(s->dump_timer, qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + s->dump_ms);
}

static void omap5430_dump_init(OMAP5430DSSState *s)
{
    const char *path = getenv("IDEMU_DSS_FRAME");
    int fd;

    if (!path || !*path) {
        return;
    }
    s->dump_size = DUMP_HDR + (size_t)1920 * 1080 * 3;
    fd = open(path, O_RDWR | O_CREAT | O_TRUNC, 0644);
    if (fd < 0 || ftruncate(fd, s->dump_size) != 0) {
        qemu_log_mask(LOG_GUEST_ERROR, "omap5430-dss: cannot create %s\n", path);
        if (fd >= 0) {
            close(fd);
        }
        return;
    }
    s->dump_map = mmap(NULL, s->dump_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (s->dump_map == MAP_FAILED) {
        s->dump_map = NULL;
        return;
    }
    s->dump_rgb = g_malloc(s->dump_size - DUMP_HDR);
    s->dump_ms = getenv("IDEMU_DSS_FRAME_MS") ? atoi(getenv("IDEMU_DSS_FRAME_MS")) : 33;
    if (s->dump_ms < 5) {
        s->dump_ms = 5;
    }
    s->dump_timer = timer_new_ms(QEMU_CLOCK_REALTIME, omap5430_dump_frame, s);
    timer_mod(s->dump_timer, qemu_clock_get_ms(QEMU_CLOCK_REALTIME) + s->dump_ms);
}

static void omap5430_invalidate_display(void *opaque)
{
    OMAP5430DSSState *s = opaque;
    s->invalidate = 1;
}

static const GraphicHwOps omap5430_gfx_ops = {
    .invalidate = omap5430_invalidate_display,
    .gfx_update = omap5430_update_display,
};

static const Property omap5430_dss_properties[] = {
    DEFINE_PROP_LINK("system-memory", OMAP5430DSSState, sysmem,
                     TYPE_MEMORY_REGION, MemoryRegion *),
    DEFINE_PROP_BOOL("trace-dmm", OMAP5430DSSState, trace_dmm, false),
};

static void omap5430_dss_realize(DeviceState *dev, Error **errp)
{
    OMAP5430DSSState *s = OMAP5430_DSS(dev);
    SysBusDevice *sbd = SYS_BUS_DEVICE(dev);
    unsigned i;

    if (!s->sysmem) {
        error_setg(errp, "system-memory property must be set");
        return;
    }
    for (i = 0; i < OMAP5430_WINDOW_COUNT; i++) {
        OMAP5430Window *w = &s->windows[i];
        w->dss = s;
        w->base = omap5430_windows[i].base;
        w->size = omap5430_windows[i].size;
        w->name = omap5430_windows[i].name;
        w->reg_count = w->size / sizeof(uint32_t);
        w->regs = g_new0(uint32_t, w->reg_count);
        memory_region_init_io(&w->iomem, OBJECT(s), &omap5430_mmio_ops, w,
                              w->name, w->size);
        sysbus_init_mmio(sbd, &w->iomem);
    }
    sysbus_init_irq(sbd, &s->dmm_irq);
    sysbus_init_irq(sbd, &s->dispc_irq);
    s->frame_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, omap5430_frame, s);

    s->invalidate = 1;
    s->con = qemu_graphic_console_create(dev, 0, &omap5430_gfx_ops, s);
    qemu_console_resize(s->con, 1280, 480);
    omap5430_dump_init(s);
}

void omap5430_dss_map(SysBusDevice *sbd)
{
    unsigned i;

    for (i = 0; i < OMAP5430_WINDOW_COUNT; i++) {
        sysbus_mmio_map(sbd, i, omap5430_windows[i].base);
    }
}

static void omap5430_dss_finalize(Object *obj)
{
    OMAP5430DSSState *s = OMAP5430_DSS(obj);
    unsigned i;

    timer_free(s->frame_timer);
    if (s->con) {
        qemu_graphic_console_close(s->con);
    }
    for (i = 0; i < OMAP5430_WINDOW_COUNT; i++) {
        g_free(s->windows[i].regs);
    }
}

/* Window sizes are machine constants, never supplied by the snapshot. */
static const VMStateDescription vmstate_omap5430_window = {
    .name = "omap5430-dss/window",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_VARRAY_UINT32(regs, OMAP5430Window, reg_count, 1,
                             vmstate_info_uint32, uint32_t),
        VMSTATE_END_OF_LIST()
    },
};

static int omap5430_dss_post_load(void *opaque, int version_id)
{
    OMAP5430DSSState *s = opaque;
    uint32_t *dss = s->windows[0].regs;
    uint32_t *dmm = s->windows[1].regs;

    qemu_set_irq(s->dispc_irq,
        (dss[(DSS_DISPC_BASE + DISPC_IRQSTATUS) / 4] &
         dss[(DSS_DISPC_BASE + DISPC_IRQENABLE) / 4]) != 0);
    qemu_set_irq(s->dmm_irq,
        (dmm[DMM_PAT_IRQSTATUS / 4] & dmm[DMM_PAT_IRQENABLE_SET / 4]) != 0);
    s->invalidate = 1;
    return 0;
}

static const VMStateDescription vmstate_omap5430_dss = {
    .name = "omap5430-dss",
    .version_id = 1,
    .minimum_version_id = 1,
    .post_load = omap5430_dss_post_load,
    .fields = (const VMStateField[]) {
        VMSTATE_STRUCT_ARRAY(windows, OMAP5430DSSState, OMAP5430_WINDOW_COUNT,
                             1, vmstate_omap5430_window, OMAP5430Window),
        VMSTATE_TIMER_PTR(frame_timer, OMAP5430DSSState),
        VMSTATE_BOOL(digital_odd, OMAP5430DSSState),
        VMSTATE_END_OF_LIST()
    },
};

static void omap5430_dss_class_init(ObjectClass *oc, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);

    set_bit(DEVICE_CATEGORY_DISPLAY, dc->categories);
    dc->realize = omap5430_dss_realize;
    dc->vmsd = &vmstate_omap5430_dss;
    device_class_set_props(dc, omap5430_dss_properties);
}

static const TypeInfo omap5430_dss_info = {
    .name = TYPE_OMAP5430_DSS,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(OMAP5430DSSState),
    .class_init = omap5430_dss_class_init,
    .instance_finalize = omap5430_dss_finalize,
};

static void omap5430_dss_register_types(void)
{
    type_register_static(&omap5430_dss_info);
}

type_init(omap5430_dss_register_types)
