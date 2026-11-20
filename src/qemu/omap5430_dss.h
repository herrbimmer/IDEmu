/*
 * OMAP5430 DSS framebuffer support for the BMW NBTevo QNX guest.
 * Origin: hw/display/omap5430_dss.h of agent00jackson/bimmulator
 * (https://github.com/agent00jackson/bimmulator), commit bf03f2e,
 * nix/patches/qemu/0001-omap5-core.patch; unchanged except these origin lines.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#ifndef HW_DISPLAY_OMAP5430_DSS_H
#define HW_DISPLAY_OMAP5430_DSS_H

#include "hw/core/sysbus.h"

#define TYPE_OMAP5430_DSS "omap5430-dss"
OBJECT_DECLARE_SIMPLE_TYPE(OMAP5430DSSState, OMAP5430_DSS)

void omap5430_dss_map(SysBusDevice *sbd);

#endif
