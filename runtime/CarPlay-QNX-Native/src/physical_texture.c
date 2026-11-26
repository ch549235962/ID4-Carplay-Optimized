/* Emulator bridge extension. SPDX-License-Identifier: GPL-3.0-only */
#include <stdint.h>
extern void nbt_send_simple(uint32_t op,int count,...);
__attribute__((visibility("default"))) void nbtTexImagePhysical(uint32_t physical,uint32_t width,uint32_t height){
    nbt_send_simple(145,3,physical,width,height);
}
