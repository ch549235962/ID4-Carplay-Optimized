/* Already decoded QNX pixels; graphics upload only. SPDX-License-Identifier: GPL-3.0-only */
#ifndef ID4_PHYSICAL_TEXTURE_UPLOAD_H
#define ID4_PHYSICAL_TEXTURE_UPLOAD_H
#include <GLES2/gl2.h>
#include "physical_texture_validate.h"
static void id4_physical_texture_upload(const void *ram,const uint8_t *p){
    __sync_synchronize();
    glTexImage2D(GL_TEXTURE_2D,0,GL_LUMINANCE,id4_u32(p+4),id4_u32(p+8),0,
        GL_LUMINANCE,GL_UNSIGNED_BYTE,(const uint8_t*)ram+id4_u32(p));
}
#endif
