/*
 * OMAP5430 SDMA register and unsynchronised transfer model.
 *
 * Register semantics follow the former QEMU OMAP DMA4 model and the Linux
 * OMAP DMA driver. External request lines, linked descriptors, indexed
 * addressing and peripheral-specific synchronization are not implemented.
 *
 * Origin: hw/dma/omap5430_sdma.c of agent00jackson/bimmulator
 * (https://github.com/agent00jackson/bimmulator), commit bf03f2e,
 * nix/patches/qemu/0001-omap5-core.patch; unchanged except these origin lines.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include "qemu/osdep.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/sysbus.h"
#include "hw/dma/omap5430_sdma.h"
#include "qemu/log.h"
#include "qemu/module.h"
#include "migration/vmstate.h"
#include "qemu/timer.h"
#include "system/address-spaces.h"

#define SDMA_BASE              0x4a056000
#define SDMA_SIZE              0x1000
#define SDMA_CHANNELS          32
#define SDMA_IRQS              4
#define SDMA_CHANNEL_BASE      0x80
#define SDMA_CHANNEL_STRIDE    0x60
#define SDMA_MAX_ELEMENTS      (1U << 20)
/* Approximate latency; transfers must not complete inside the CCR write. */
#define SDMA_TRANSFER_DELAY_NS (10 * 1000 * 1000)

#define SDMA_IRQSTATUS_BASE    0x08
#define SDMA_IRQENABLE_BASE    0x18
#define SDMA_SYSSTATUS         0x28
#define SDMA_SYSCONFIG         0x2c
#define SDMA_GCR               0x78

#define SDMA_CCR               0x00
#define SDMA_CICR              0x08
#define SDMA_CSR               0x0c
#define SDMA_CSDP              0x10
#define SDMA_CEN               0x14
#define SDMA_CFN               0x18
#define SDMA_CSSA              0x1c
#define SDMA_CDSA              0x20
#define SDMA_CSAC              0x34
#define SDMA_CDAC              0x38
#define SDMA_CCEN              0x3c
#define SDMA_CCFN              0x40

#define SDMA_CCR_ENABLE        (1U << 7)
#define SDMA_CCR_FILL          (1U << 16)
#define SDMA_CCR_TRANSPARENT   (1U << 17)
#define SDMA_CSR_FRAME         (1U << 3)
#define SDMA_CSR_BLOCK         (1U << 5)
#define SDMA_CSR_TRANS_ERR     (1U << 8)
#define SDMA_CSR_MISALIGN      (1U << 11)

typedef struct OMAP5430SDMAChannel {
    uint32_t regs[SDMA_CHANNEL_STRIDE / 4];
    OMAP5430SDMAState *controller;
    unsigned index;
    QEMUTimer *timer;
} OMAP5430SDMAChannel;

struct OMAP5430SDMAState {
    SysBusDevice parent_obj;
    MemoryRegion iomem;
    qemu_irq irq[SDMA_IRQS];
    uint32_t global[SDMA_CHANNEL_BASE / 4];
    uint32_t irq_status[SDMA_IRQS];
    uint32_t irq_enable[SDMA_IRQS];
    OMAP5430SDMAChannel channel[SDMA_CHANNELS];
    bool trace;
};

static void sdma_update_irqs(OMAP5430SDMAState *s)
{
    unsigned i;

    for (i = 0; i < SDMA_IRQS; i++) {
        qemu_set_irq(s->irq[i], (s->irq_status[i] & s->irq_enable[i]) != 0);
    }
}

static void sdma_complete(OMAP5430SDMAState *s, unsigned n, uint32_t status)
{
    OMAP5430SDMAChannel *ch = &s->channel[n];
    unsigned i;

    ch->regs[SDMA_CCR / 4] &= ~SDMA_CCR_ENABLE;
    ch->regs[SDMA_CSR / 4] |= status;
    if (status & ch->regs[SDMA_CICR / 4]) {
        for (i = 0; i < SDMA_IRQS; i++) {
            s->irq_status[i] |= s->irq_enable[i] & (1U << n);
        }
    }
    if (s->trace) {
        qemu_log_mask(LOG_GUEST_ERROR,
                      "omap5430-sdma: ch%u status=%#x irq=%#x/%#x/%#x/%#x\n",
                      n, status, s->irq_status[0], s->irq_status[1],
                      s->irq_status[2], s->irq_status[3]);
    }
    sdma_update_irqs(s);
}

static void sdma_transfer(OMAP5430SDMAState *s, unsigned n)
{
    OMAP5430SDMAChannel *ch = &s->channel[n];
    uint32_t ccr = ch->regs[SDMA_CCR / 4];
    uint32_t csdp = ch->regs[SDMA_CSDP / 4];
    uint32_t elements = ch->regs[SDMA_CEN / 4] & 0xffffff;
    uint32_t frames = ch->regs[SDMA_CFN / 4] & 0xffff;
    uint32_t src = ch->regs[SDMA_CSSA / 4];
    uint32_t dst = ch->regs[SDMA_CDSA / 4];
    unsigned src_mode = (ccr >> 12) & 3;
    unsigned dst_mode = (ccr >> 14) & 3;
    unsigned width = 1U << (csdp & 3);
    uint32_t request = (ccr & 0x1f) | ((ccr >> 14) & 0x60);
    uint32_t f, e;

    if (s->trace) {
        qemu_log_mask(LOG_GUEST_ERROR,
                      "omap5430-sdma: ch%u ccr=%#x csdp=%#x src=%#x dst=%#x "
                      "elements=%u frames=%u request=%u\n",
                      n, ccr, csdp, src, dst, elements, frames, request);
    }
    if (request) {
        /* Hardware-synchronized transfers wait for their peripheral request. */
        qemu_log_mask(LOG_UNIMP,
                      "omap5430-sdma: external request %u is not modelled\n",
                      request);
        return;
    }
    if (width > 4 || !elements || !frames ||
        (uint64_t)elements * frames > SDMA_MAX_ELEMENTS ||
        src_mode > 1 || dst_mode > 1 ||
        (ccr & (SDMA_CCR_FILL | SDMA_CCR_TRANSPARENT)) ||
        ((csdp >> 21) & 1) != ((csdp >> 19) & 1)) {
        qemu_log_mask(LOG_UNIMP,
                      "omap5430-sdma: unsupported transfer on channel %u\n", n);
        sdma_complete(s, n, SDMA_CSR_TRANS_ERR);
        return;
    }
    if ((src | dst) & (width - 1)) {
        sdma_complete(s, n, SDMA_CSR_MISALIGN);
        return;
    }

    for (f = 0; f < frames; f++) {
        for (e = 0; e < elements; e++) {
            uint8_t data[4];
            MemTxResult result;

            /* Avoid a recursive write into this controller's own registers. */
            if ((src >= SDMA_BASE && src < SDMA_BASE + SDMA_SIZE) ||
                (dst >= SDMA_BASE && dst < SDMA_BASE + SDMA_SIZE)) {
                sdma_complete(s, n, SDMA_CSR_TRANS_ERR);
                return;
            }
            result = address_space_read(&address_space_memory, src,
                                        MEMTXATTRS_UNSPECIFIED, data, width);
            if (result == MEMTX_OK) {
                result = address_space_write(&address_space_memory, dst,
                                             MEMTXATTRS_UNSPECIFIED, data, width);
            }
            if (result != MEMTX_OK) {
                sdma_complete(s, n, SDMA_CSR_TRANS_ERR);
                return;
            }
            if (src_mode == 1) {
                src += width;
            }
            if (dst_mode == 1) {
                dst += width;
            }
        }
    }
    ch->regs[SDMA_CSAC / 4] = src;
    ch->regs[SDMA_CDAC / 4] = dst;
    ch->regs[SDMA_CCEN / 4] = elements;
    ch->regs[SDMA_CCFN / 4] = frames;
    sdma_complete(s, n, SDMA_CSR_FRAME | SDMA_CSR_BLOCK);
}

static void sdma_timer(void *opaque)
{
    OMAP5430SDMAChannel *ch = opaque;

    if (ch->regs[SDMA_CCR / 4] & SDMA_CCR_ENABLE) {
        sdma_transfer(ch->controller, ch->index);
    }
}

static uint64_t sdma_read(void *opaque, hwaddr offset, unsigned size)
{
    OMAP5430SDMAState *s = opaque;
    unsigned channel, reg;

    if (offset == 0) {
        return 0x40; /* DMA4 revision */
    }
    if (offset >= SDMA_IRQSTATUS_BASE && offset < SDMA_IRQSTATUS_BASE + 16) {
        return s->irq_status[(offset - SDMA_IRQSTATUS_BASE) / 4];
    }
    if (offset >= SDMA_IRQENABLE_BASE && offset < SDMA_IRQENABLE_BASE + 16) {
        return s->irq_enable[(offset - SDMA_IRQENABLE_BASE) / 4];
    }
    if (offset == SDMA_SYSSTATUS) {
        return 1; /* reset complete */
    }
    if (offset < SDMA_CHANNEL_BASE) {
        return s->global[offset / 4];
    }
    channel = (offset - SDMA_CHANNEL_BASE) / SDMA_CHANNEL_STRIDE;
    reg = (offset - SDMA_CHANNEL_BASE) % SDMA_CHANNEL_STRIDE;
    if (channel >= SDMA_CHANNELS) {
        return 0;
    }
    return s->channel[channel].regs[reg / 4];
}

static void sdma_reset(DeviceState *dev)
{
    OMAP5430SDMAState *s = OMAP5430_SDMA(dev);
    unsigned i;

    for (i = 0; i < SDMA_CHANNELS; i++) {
        timer_del(s->channel[i].timer);
        memset(s->channel[i].regs, 0, sizeof(s->channel[i].regs));
    }
    memset(s->global, 0, sizeof(s->global));
    memset(s->irq_status, 0, sizeof(s->irq_status));
    memset(s->irq_enable, 0, sizeof(s->irq_enable));
    s->global[SDMA_GCR / 4] = 0x00010010;
    sdma_update_irqs(s);
}

static void sdma_write(void *opaque, hwaddr offset, uint64_t value,
                       unsigned size)
{
    OMAP5430SDMAState *s = opaque;
    OMAP5430SDMAChannel *ch;
    uint32_t old;
    unsigned channel, reg;

    if (s->trace) {
        qemu_log_mask(LOG_GUEST_ERROR, "omap5430-sdma: write %#" HWADDR_PRIx
                      " = %#" PRIx64 "\n", offset, value);
    }
    if (offset >= SDMA_IRQSTATUS_BASE && offset < SDMA_IRQSTATUS_BASE + 16) {
        s->irq_status[(offset - SDMA_IRQSTATUS_BASE) / 4] &= ~(uint32_t)value;
        sdma_update_irqs(s);
        return;
    }
    if (offset >= SDMA_IRQENABLE_BASE && offset < SDMA_IRQENABLE_BASE + 16) {
        s->irq_enable[(offset - SDMA_IRQENABLE_BASE) / 4] = value;
        sdma_update_irqs(s);
        return;
    }
    if (offset == SDMA_SYSCONFIG && (value & 2)) {
        sdma_reset(DEVICE(s));
        return;
    }
    if (offset < SDMA_CHANNEL_BASE) {
        if (offset != 0 && offset != SDMA_SYSSTATUS) {
            s->global[offset / 4] = value;
        }
        return;
    }
    channel = (offset - SDMA_CHANNEL_BASE) / SDMA_CHANNEL_STRIDE;
    reg = (offset - SDMA_CHANNEL_BASE) % SDMA_CHANNEL_STRIDE;
    if (channel >= SDMA_CHANNELS) {
        return;
    }
    ch = &s->channel[channel];
    old = ch->regs[reg / 4];
    if (reg == SDMA_CSR) {
        ch->regs[reg / 4] &= ~(uint32_t)value;
    } else if (reg != SDMA_CSAC && reg != SDMA_CDAC &&
               reg != SDMA_CCEN && reg != SDMA_CCFN) {
        ch->regs[reg / 4] = value;
    }
    if (reg == SDMA_CCR && !(old & SDMA_CCR_ENABLE) &&
        (value & SDMA_CCR_ENABLE)) {
        timer_mod(ch->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  SDMA_TRANSFER_DELAY_NS);
    } else if (reg == SDMA_CCR && !(value & SDMA_CCR_ENABLE)) {
        timer_del(ch->timer);
    }
}

static const MemoryRegionOps sdma_ops = {
    .read = sdma_read,
    .write = sdma_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
};

static void sdma_realize(DeviceState *dev, Error **errp)
{
    OMAP5430SDMAState *s = OMAP5430_SDMA(dev);
    unsigned i;

    memory_region_init_io(&s->iomem, OBJECT(s), &sdma_ops, s,
                          "omap5430-sdma", SDMA_SIZE);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->iomem);
    for (i = 0; i < SDMA_IRQS; i++) {
        sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq[i]);
    }
    for (i = 0; i < SDMA_CHANNELS; i++) {
        s->channel[i].controller = s;
        s->channel[i].index = i;
        s->channel[i].timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, sdma_timer,
                                           &s->channel[i]);
    }
    sdma_reset(dev);
}

static void sdma_unrealize(DeviceState *dev)
{
    OMAP5430SDMAState *s = OMAP5430_SDMA(dev);
    unsigned i;

    for (i = 0; i < SDMA_CHANNELS; i++) {
        timer_free(s->channel[i].timer);
    }
}

static const Property sdma_properties[] = {
    DEFINE_PROP_BOOL("trace", OMAP5430SDMAState, trace, false),
};

static const VMStateDescription vmstate_omap5430_sdma_channel = {
    .name = "omap5430-sdma/channel",
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT32_ARRAY(regs, OMAP5430SDMAChannel, SDMA_CHANNEL_STRIDE / 4),
        VMSTATE_TIMER_PTR(timer, OMAP5430SDMAChannel),
        VMSTATE_END_OF_LIST()
    },
};

static int sdma_post_load(void *opaque, int version_id)
{
    sdma_update_irqs(opaque);
    return 0;
}

static const VMStateDescription vmstate_omap5430_sdma = {
    .name = "omap5430-sdma",
    .version_id = 1,
    .minimum_version_id = 1,
    .post_load = sdma_post_load,
    .fields = (const VMStateField[]) {
        VMSTATE_UINT32_ARRAY(global, OMAP5430SDMAState, SDMA_CHANNEL_BASE / 4),
        VMSTATE_UINT32_ARRAY(irq_status, OMAP5430SDMAState, SDMA_IRQS),
        VMSTATE_UINT32_ARRAY(irq_enable, OMAP5430SDMAState, SDMA_IRQS),
        VMSTATE_STRUCT_ARRAY(channel, OMAP5430SDMAState, SDMA_CHANNELS,
                             1, vmstate_omap5430_sdma_channel, OMAP5430SDMAChannel),
        VMSTATE_END_OF_LIST()
    },
};

static void sdma_class_init(ObjectClass *oc, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(oc);

    dc->realize = sdma_realize;
    dc->vmsd = &vmstate_omap5430_sdma;
    dc->unrealize = sdma_unrealize;
    device_class_set_legacy_reset(dc, sdma_reset);
    device_class_set_props(dc, sdma_properties);
}

static const TypeInfo sdma_info = {
    .name = TYPE_OMAP5430_SDMA,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(OMAP5430SDMAState),
    .class_init = sdma_class_init,
};

static void sdma_register_types(void)
{
    type_register_static(&sdma_info);
}

type_init(sdma_register_types)
