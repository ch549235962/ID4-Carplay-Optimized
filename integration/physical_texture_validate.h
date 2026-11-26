/* Local bounded YUV transport. SPDX-License-Identifier: GPL-3.0-only */
#ifndef ID4_PHYSICAL_TEXTURE_VALIDATE_H
#define ID4_PHYSICAL_TEXTURE_VALIDATE_H
#include <stdint.h>
static uint32_t id4_u32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int id4_physical_texture_valid(const uint8_t *p,uint32_t length){
    if(length!=12)return 0;
    uint32_t physical=id4_u32(p),width=id4_u32(p+4),height=id4_u32(p+8);
    return width>0&&width<=1280&&height>0&&height<=480&&physical>=0x100000&&
        (uint64_t)physical+(uint64_t)width*height<=0x20000000ull;
}
#endif
