/*
 * OMAP5430 system DMA controller.
 * Origin: hw/dma/omap5430_sdma.h of agent00jackson/bimmulator
 * (https://github.com/agent00jackson/bimmulator), commit bf03f2e,
 * nix/patches/qemu/0001-omap5-core.patch. The original has only the first
 * line of this comment; IDEmu added the rest (origin and SPDX tag, the
 * licence of the patch it comes from). The code is unchanged.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef HW_DMA_OMAP5430_SDMA_H
#define HW_DMA_OMAP5430_SDMA_H

#include "qom/object.h"

#define TYPE_OMAP5430_SDMA "omap5430-sdma"
OBJECT_DECLARE_SIMPLE_TYPE(OMAP5430SDMAState, OMAP5430_SDMA)

#endif
