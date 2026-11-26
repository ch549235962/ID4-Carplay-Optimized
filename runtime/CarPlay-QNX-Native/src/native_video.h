/* Local QNX emulator display backend. SPDX-License-Identifier: GPL-3.0-only */
#ifndef NATIVE_VIDEO_H
#define NATIVE_VIDEO_H
#include <stdint.h>
#define NV_MAGIC 0x4e565131u
#define NV_WIDTH 1280
#define NV_HEIGHT 480
#define NV_BYTES (NV_WIDTH * NV_HEIGHT * 3 / 2)
#define NV_PATH "/nbt-carplay-video-v1"
struct nv_slot {
    volatile uint32_t generation;
    uint32_t width, height, full_range; /* flags: bit 0 full range, bit 1 BT.709 */
    uint8_t pixels[NV_BYTES]; /* tightly packed Y, U, V */
};
struct nv_shared {
    uint32_t magic, version;
    volatile uint32_t latest, decoded, errors, active;
    volatile uint32_t rendered, render_errors;
    struct nv_slot slots[3];
};
#endif
