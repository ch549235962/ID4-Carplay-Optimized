/* Native QNX EGL display adapter for the local emulator's GLES bridge.
 * It runs in HmiMain3D and samples frames decoded by a QNX process.
 * SPDX-License-Identifier: GPL-3.0-only
 */
#define _QNX_SOURCE 1
#include <GLES2/gl2.h>
#include <dlfcn.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdint.h>
#include <pthread.h>
#include <sched.h>
#include <sys/neutrino.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "native_video.h"

struct attribute { GLint size; GLenum type; GLboolean norm; GLsizei stride; const void *ptr; GLuint buffer; int set,enabled; };
static __thread struct {
    int inside;
    GLuint program,array_buffer,framebuffer,texture[3];
    GLenum active;
    GLint viewport[4],unpack;
    GLboolean color[4];
    int viewport_set,color_set,blend,depth,stencil,scissor,cull;
    struct attribute attr[16];
} state;

#define NEXT(name) static __typeof__(&name) real; if(!real)real=dlsym(RTLD_NEXT,#name)
void glUseProgram(GLuint p){NEXT(glUseProgram);if(!state.inside)state.program=p;real(p);}
void glActiveTexture(GLenum t){NEXT(glActiveTexture);if(!state.inside)state.active=t;real(t);}
void glBindTexture(GLenum t,GLuint n){NEXT(glBindTexture);unsigned u=(state.active?state.active:GL_TEXTURE0)-GL_TEXTURE0;if(!state.inside&&t==GL_TEXTURE_2D&&u<3)state.texture[u]=n;real(t,n);}
void glBindBuffer(GLenum t,GLuint n){NEXT(glBindBuffer);if(!state.inside&&t==GL_ARRAY_BUFFER)state.array_buffer=n;real(t,n);}
void glBindFramebuffer(GLenum t,GLuint n){NEXT(glBindFramebuffer);if(!state.inside&&t==GL_FRAMEBUFFER)state.framebuffer=n;real(t,n);}
void glViewport(GLint x,GLint y,GLsizei w,GLsizei h){NEXT(glViewport);if(!state.inside){state.viewport[0]=x;state.viewport[1]=y;state.viewport[2]=w;state.viewport[3]=h;state.viewport_set=1;}real(x,y,w,h);}
void glColorMask(GLboolean a,GLboolean b,GLboolean c,GLboolean d){NEXT(glColorMask);if(!state.inside){state.color[0]=a;state.color[1]=b;state.color[2]=c;state.color[3]=d;state.color_set=1;}real(a,b,c,d);}
void glPixelStorei(GLenum p,GLint n){NEXT(glPixelStorei);if(!state.inside&&p==GL_UNPACK_ALIGNMENT)state.unpack=n;real(p,n);}
static void capability(GLenum cap,int enabled){switch(cap){case GL_BLEND:state.blend=enabled;break;case GL_DEPTH_TEST:state.depth=enabled;break;case GL_STENCIL_TEST:state.stencil=enabled;break;case GL_SCISSOR_TEST:state.scissor=enabled;break;case GL_CULL_FACE:state.cull=enabled;break;}}
void glEnable(GLenum c){NEXT(glEnable);if(!state.inside)capability(c,1);real(c);}
void glDisable(GLenum c){NEXT(glDisable);if(!state.inside)capability(c,0);real(c);}
void glVertexAttribPointer(GLuint i,GLint s,GLenum t,GLboolean n,GLsizei stride,const void *p){NEXT(glVertexAttribPointer);if(!state.inside&&i<16){struct attribute *a=&state.attr[i];a->size=s;a->type=t;a->norm=n;a->stride=stride;a->ptr=p;a->buffer=state.array_buffer;a->set=1;}real(i,s,t,n,stride,p);}
void glEnableVertexAttribArray(GLuint i){NEXT(glEnableVertexAttribArray);if(!state.inside&&i<16)state.attr[i].enabled=1;real(i);}
void glDisableVertexAttribArray(GLuint i){NEXT(glDisableVertexAttribArray);if(!state.inside&&i<16)state.attr[i].enabled=0;real(i);}

static struct nv_shared *shared;
static GLuint program,textures[3],vbo;
static unsigned last_number,last_generation,draws;
static GLint matrix_location,yscale_location;
static uint8_t pixels[NV_BYTES];
static uint8_t *staging=pixels;
static uint32_t staging_physical;
static void (*physical_texture)(uint32_t,uint32_t,uint32_t);

/* Same pinned 3D1407 display readiness check as emulator_ready.c. Let the
 * original EGL calls return during startup so HMI can enable its display and
 * finish registering iDrive input before CarPlay owns the presentation loop. */
static int stock_display_ready(void){
    if(memcmp((void*)0x88e2f92,"\x55\x89\xe5\x56\x53\x0f\xb7\x1d\x44\x26\x9a\x09",12))return 0;
    if(!*(volatile unsigned char*)0x98c0f50||!*(volatile unsigned short*)0x99a2644)return 0;
    void *legacy=((void*(*)(void))(uintptr_t)0x80b45d8)();
    if(!legacy||!*(unsigned*)((char*)legacy+0xc4))return 0;
    void *context=((void*(*)(void*))(uintptr_t)0x80b007e)(legacy);
    if(!context)return 0;
    uint32_t vt=*(uint32_t*)context;
    void *display=((void*(*)(void*,int))(uintptr_t)(*(uint32_t*)(vt+0x10)))(context,0x1f);
    return display&&*((volatile unsigned char*)display+0x31);
}

static GLuint shader(GLenum type,const char *source){
    GLuint id=glCreateShader(type);GLint ok=0;
    glShaderSource(id,1,&source,0);glCompileShader(id);glGetShaderiv(id,GL_COMPILE_STATUS,&ok);
    if(!ok){fprintf(stderr,"QNX_NATIVE_OVERLAY_SHADER_FAILED type=%u\n",type);return 0;}return id;
}

static int initialize(void){
    void *bridge=dlopen("libnbtgl.so",RTLD_LAZY);
    if(bridge)physical_texture=dlsym(bridge,"nbtTexImagePhysical");
    if(physical_texture&&ThreadCtl(_NTO_TCTL_IO,0)!=-1){
        void *buffer=mmap(0,NV_BYTES,PROT_READ|PROT_WRITE,MAP_PHYS|MAP_ANON|MAP_SHARED,NOFD,0);
        off64_t phys=0;size_t contiguous=0;
        if(buffer!=MAP_FAILED&&!mem_offset64(buffer,NOFD,NV_BYTES,&phys,&contiguous)&&
           contiguous>=NV_BYTES&&phys>=0x100000&&phys+NV_BYTES<=0x20000000){
            staging=buffer;staging_physical=(uint32_t)phys;
            fprintf(stderr,"QNX_NATIVE_PHYSICAL_TEXTURE_READY physical=%x bytes=%u\n",staging_physical,NV_BYTES);
        }else{if(buffer!=MAP_FAILED)munmap(buffer,NV_BYTES);physical_texture=0;}
    }else physical_texture=0;
    const char *vs="attribute vec2 position; varying vec2 uv; void main(){gl_Position=vec4(position,0.,1.);uv=vec2((position.x+1.)*.5,(1.-position.y)*.5);}";
    const char *fs="precision mediump float; varying vec2 uv; uniform sampler2D yy; uniform sampler2D uu; uniform sampler2D vv; uniform vec4 matrix; uniform vec2 yscale; void main(){float y=texture2D(yy,uv).r*yscale.x+yscale.y;float u=texture2D(uu,uv).r-.5;float v=texture2D(vv,uv).r-.5;gl_FragColor=vec4(y+matrix.x*v,y+matrix.y*u+matrix.z*v,y+matrix.w*u,1.);}";
    GLuint a=shader(GL_VERTEX_SHADER,vs),b=shader(GL_FRAGMENT_SHADER,fs);GLint ok=0;
    if(!a||!b)return -1;
    program=glCreateProgram();glAttachShader(program,a);glAttachShader(program,b);
    glBindAttribLocation(program,0,"position");glLinkProgram(program);glGetProgramiv(program,GL_LINK_STATUS,&ok);
    if(!ok){program=0;return -1;}
    glGenTextures(3,textures);glGenBuffers(1,&vbo);
    glUseProgram(program);
    const char *names[]={"yy","uu","vv"};
    for(unsigned i=0;i<3;i++){
        glActiveTexture(GL_TEXTURE0+i);glBindTexture(GL_TEXTURE_2D,textures[i]);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
        glUniform1i(glGetUniformLocation(program,names[i]),i);
    }
    matrix_location=glGetUniformLocation(program,"matrix");yscale_location=glGetUniformLocation(program,"yscale");
    static const GLfloat quad[]={-1,-1,1,-1,-1,1,1,1};
    glBindBuffer(GL_ARRAY_BUFFER,vbo);glBufferData(GL_ARRAY_BUFFER,sizeof(quad),quad,GL_STATIC_DRAW);
    fprintf(stderr,"QNX_NATIVE_OVERLAY_READY backend=guest-GLES-shared-YUV\n");return 0;
}

static void restore(void){
    for(unsigned i=0;i<16;i++){
        if(i==0){struct attribute *a=&state.attr[i];glBindBuffer(GL_ARRAY_BUFFER,a->set?a->buffer:0);glVertexAttribPointer(i,a->set?a->size:4,a->set?a->type:GL_FLOAT,a->norm,a->stride,a->ptr);}
        if(state.attr[i].enabled)glEnableVertexAttribArray(i);else glDisableVertexAttribArray(i);
    }
    glBindBuffer(GL_ARRAY_BUFFER,state.array_buffer);glBindFramebuffer(GL_FRAMEBUFFER,state.framebuffer);
    for(unsigned i=0;i<3;i++){glActiveTexture(GL_TEXTURE0+i);glBindTexture(GL_TEXTURE_2D,state.texture[i]);}
    glActiveTexture(state.active?state.active:GL_TEXTURE0);glUseProgram(state.program);
    const GLenum caps[]={GL_BLEND,GL_DEPTH_TEST,GL_STENCIL_TEST,GL_SCISSOR_TEST,GL_CULL_FACE};
    const int enabled[]={state.blend,state.depth,state.stencil,state.scissor,state.cull};
    for(unsigned i=0;i<5;i++){if(enabled[i])glEnable(caps[i]);else glDisable(caps[i]);}
    if(state.viewport_set)glViewport(state.viewport[0],state.viewport[1],state.viewport[2],state.viewport[3]);
    glPixelStorei(GL_UNPACK_ALIGNMENT,state.unpack?state.unpack:4);
    if(state.color_set)glColorMask(state.color[0],state.color[1],state.color[2],state.color[3]);else glColorMask(1,1,1,1);
}

static int draw(int only_fresh){
    if(access("/var/tmp/nbt-native/show-video",F_OK))return 0;
    if(!shared){int fd=shm_open(NV_PATH,O_RDWR,0);if(fd<0)return 0;shared=mmap(0,sizeof(*shared),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);if(shared==MAP_FAILED){shared=0;return 0;}}
    if(shared->magic!=NV_MAGIC||shared->version!=1||!shared->decoded||!shared->active)return 0;
    unsigned number=shared->decoded,index=shared->latest;
    if(index>=3)return 0;
    struct nv_slot *s=&shared->slots[index];unsigned generation=s->generation;
    if(generation&1)return 0;
    __sync_synchronize();unsigned w=s->width,h=s->height,flags=s->full_range;
    if(w<2||h<2||w>NV_WIDTH||h>NV_HEIGHT||(w&1)||(h&1))return 0;
    int fresh=number!=last_number||generation!=last_generation;
    if(only_fresh&&!fresh)return 0;
    state.inside=1;
    if(!program&&initialize()){shared->render_errors++;restore();state.inside=0;return 0;}
    if(fresh){memcpy(staging,s->pixels,w*h*3/2);__sync_synchronize();if(generation!=s->generation){restore();state.inside=0;return 0;}}
    glBindFramebuffer(GL_FRAMEBUFFER,0);glViewport(0,0,1280,480);glColorMask(1,1,1,1);
    glDisable(GL_BLEND);glDisable(GL_DEPTH_TEST);glDisable(GL_STENCIL_TEST);glDisable(GL_SCISSOR_TEST);glDisable(GL_CULL_FACE);
    glUseProgram(program);glPixelStorei(GL_UNPACK_ALIGNMENT,1);
    unsigned offset=0;
    for(unsigned plane=0;plane<3;plane++){
        unsigned pw=w>>(plane!=0),ph=h>>(plane!=0);
        glActiveTexture(GL_TEXTURE0+plane);glBindTexture(GL_TEXTURE_2D,textures[plane]);
        if(fresh){
            if(physical_texture)physical_texture(staging_physical+offset,pw,ph);
            else glTexImage2D(GL_TEXTURE_2D,0,GL_LUMINANCE,pw,ph,0,GL_LUMINANCE,GL_UNSIGNED_BYTE,staging+offset);
        }
        offset+=pw*ph;
    }
    int full=flags&1,bt709=flags&2;
    if(bt709){if(full)glUniform4f(matrix_location,1.5748f,-.187324f,-.468124f,1.8556f);else glUniform4f(matrix_location,1.792741f,-.213249f,-.532909f,2.112402f);}
    else{if(full)glUniform4f(matrix_location,1.402f,-.344136f,-.714136f,1.772f);else glUniform4f(matrix_location,1.596027f,-.391762f,-.812968f,2.017232f);}
    glUniform2f(yscale_location,full?1.f:1.1643836f,full?0.f:-.0627451f*1.1643836f);
    glBindBuffer(GL_ARRAY_BUFFER,vbo);glVertexAttribPointer(0,2,GL_FLOAT,0,0,0);glEnableVertexAttribArray(0);
    for(unsigned i=1;i<16;i++)glDisableVertexAttribArray(i);
    glDrawArrays(GL_TRIANGLE_STRIP,0,4);
    GLenum error=glGetError();
    if(error){shared->render_errors++;if(shared->render_errors<4)fprintf(stderr,"QNX_NATIVE_OVERLAY_GL_ERROR=%u\n",error);}
    else{if(number!=last_number&&(!draws||draws%300==0))fprintf(stderr,"QNX_NATIVE_OVERLAY_FRAME decoded=%u dimensions=%ux%u errors=%u\n",number,w,h,shared->render_errors);draws++;}
    last_number=number;last_generation=generation;restore();state.inside=0;
    return !error;
}

int eglSwapBuffers(void *display,void *surface){
    static int(*next)(void*,void*);if(!next)next=dlsym(RTLD_NEXT,"eglSwapBuffers");
    if(!next)return 0;
    int painted=draw(0),result=next(display,surface);
    if(painted&&result)shared->rendered++;
    /* While CarPlay owns the screen, present decoded frames on this EGL thread.
     * Returning to the stock scene between every video frame limits video to
     * the very slow emulated HMI scene rate. The hide flag immediately releases
     * this loop and resumes ordinary HMI rendering on the same context/thread.
     * Every draw restores HMI GL state; no second thread touches its context. */
    int pump_ready=painted&&result&&stock_display_ready();
    int policy=0,priority_changed=0;struct sched_param saved_priority;
    /* SSH starts the decoder at priority 16; stock HMI rendering is priority
     * 12. Give presentation precedence while it owns the screen, with a sleep
     * between polls so the decoder and input service continue to run. Restore
     * the original scheduling parameters before resuming the stock scene. */
    if(pump_ready&&!pthread_getschedparam(pthread_self(),&policy,&saved_priority)){
        struct sched_param video_priority=saved_priority;
        if(video_priority.sched_priority<17){
            video_priority.sched_priority=17;
            priority_changed=!pthread_setschedparam(pthread_self(),policy,&video_priority);
        }
    }
    while(pump_ready&&result&&!access("/var/tmp/nbt-native/show-video",F_OK)){
        if(draw(1)){
            result=next(display,surface);
            if(result)shared->rendered++;
        }
        usleep(1000);
    }
    if(priority_changed)pthread_setschedparam(pthread_self(),policy,&saved_priority);
    return result;
}
