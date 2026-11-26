/* Decode H.264 inside QNX and publish YUV frames to its shared-memory display.
 * Mac transport supplies compressed bytes only. No host-side video decoding.
 * Annex B access-unit assembly follows JayJay3071/nbt-android-auto's
 * nbt_decoder.c, Copyright (C) 2026 Valentin Radu.
 * SPDX-License-Identifier: GPL-3.0-only
 */
#define _QNX_SOURCE 1
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <libavcodec/avcodec.h>
#include "native_video.h"

static struct nv_shared *shared;
static volatile sig_atomic_t stop;
static void quit(int sig) { (void)sig; stop=1; }

static void output(const AVFrame *f) {
    unsigned slot=(shared->decoded+1)%3;
    struct nv_slot *s=&shared->slots[slot];
    if ((f->format!=AV_PIX_FMT_YUV420P && f->format!=AV_PIX_FMT_YUVJ420P) ||
        f->width<2 || f->height<2 || f->width>NV_WIDTH || f->height>NV_HEIGHT ||
        (f->width&1) || (f->height&1)) { shared->errors++; return; }
    s->generation++; __sync_synchronize();
    s->width=f->width; s->height=f->height;
    s->full_range=(f->color_range==AVCOL_RANGE_JPEG || f->format==AV_PIX_FMT_YUVJ420P ? 1u:0u) |
                  (f->colorspace==AVCOL_SPC_BT709 ? 2u:0u);
    uint8_t *out=s->pixels;
    for (int plane=0;plane<3;plane++) {
        int w=f->width>>(plane!=0),h=f->height>>(plane!=0);
        for(int y=0;y<h;y++) { memcpy(out,f->data[plane]+y*f->linesize[plane],w);out+=w; }
    }
    __sync_synchronize(); s->generation++; __sync_synchronize();
    shared->latest=slot; shared->decoded++; shared->active=1;
}

static void decode(AVCodecContext *c, AVFrame *f, uint8_t *p,int n) {
    AVPacket packet; int got=0;
    av_init_packet(&packet); packet.data=p;packet.size=n;
    if(avcodec_decode_video2(c,f,&got,&packet)<0) shared->errors++;
    else if(got) output(f);
}

int main(int argc,char **argv) {
    if(argc!=2) { fprintf(stderr,"usage: native_decoder ANNEX_B_FILE_OR_FIFO\n");return 2; }
    signal(SIGTERM,quit);signal(SIGINT,quit);signal(SIGPIPE,SIG_IGN);
    int fd=shm_open(NV_PATH,O_CREAT|O_RDWR,0600);
    if(fd<0 || ftruncate(fd,sizeof(*shared))) {perror("shm");return 2;}
    shared=mmap(0,sizeof(*shared),PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);close(fd);
    if(shared==MAP_FAILED) {perror("mmap");return 2;}
    memset(shared,0,sizeof(*shared));shared->version=1;
    for(unsigned i=0;i<3;i++)shared->slots[i].generation=(uint32_t)getpid()*2u;
    __sync_synchronize();shared->magic=NV_MAGIC;
    avcodec_register_all();
    AVCodec *codec=avcodec_find_decoder(AV_CODEC_ID_H264);
    AVCodecContext *c=avcodec_alloc_context3(codec);
    AVFrame *frame=av_frame_alloc();
    if(!c||!frame||avcodec_open2(c,codec,0)<0) {fprintf(stderr,"QNX_NATIVE_CODEC_OPEN_FAILED\n");return 2;}
    fprintf(stderr,"QNX_NATIVE_DECODER_READY ffmpeg=%s shm_bytes=%u\n",av_version_info(),(unsigned)sizeof(*shared));
    /* Upstream builds only the decoder, without FFmpeg's H.264 parser.
     * Assemble access units from Annex B NALs, as upstream nbt_decoder does. */
    enum { CAP=1<<20 };
    uint8_t *buf=malloc(CAP+AV_INPUT_BUFFER_PADDING_SIZE);
    uint8_t *au=malloc(CAP+AV_INPUT_BUFFER_PADDING_SIZE);
    if(!buf||!au)return 2;
    size_t fill=0,scan=0,au_size=0;long start=-1;int slices=0;
    fd=!strcmp(argv[1],"-")?STDIN_FILENO:open(argv[1],O_RDONLY);
    if(fd<0){perror(argv[1]);return 2;}
    while(!stop) {
        if(fill==CAP){shared->errors++;break;}
        int n=read(fd,buf+fill,CAP-fill);
        if(n<0) {if(errno==EINTR)continue;perror("read");shared->errors++;break;}
        int eof=!n;fill+=n;
        /* At EOF a synthetic start code flushes the final pending NAL. */
        if(eof){memset(buf+fill,0,4);buf[fill+2]=1;fill+=3;}
        for(size_t i=scan;i+3<=fill;i++) {
            if(buf[i]||buf[i+1]||buf[i+2]!=1)continue;
            size_t at=i&&!buf[i-1]?i-1:i;
            if(start>=0&&at>(size_t)start){
                uint8_t *nal=buf+start;size_t len=at-start,head=nal[2]==1?3:4;
                if(len>head){
                    int type=nal[head]&31,slice=type==1||type==5;
                    if(slices&&((type>=6&&type<=9)||(type>=14&&type<=18)||(slice&&len>head+1&&(nal[head+1]&128)))){
                        memset(au+au_size,0,AV_INPUT_BUFFER_PADDING_SIZE);decode(c,frame,au,au_size);au_size=0;slices=0;
                    }
                    if(type!=12){
                        if(au_size+len>CAP){shared->errors++;stop=1;break;}
                        memcpy(au+au_size,nal,len);au_size+=len;slices+=slice;
                    }
                }
            }
            start=at;
            size_t h=buf[at+2]==1?at+3:at+4;
            if(h<fill&&(buf[h]&31)==9&&slices){memset(au+au_size,0,AV_INPUT_BUFFER_PADDING_SIZE);decode(c,frame,au,au_size);au_size=0;slices=0;}
            i+=2;
        }
        if(eof)break;
        if(start>0){memmove(buf,buf+start,fill-start);fill-=start;start=0;}
        scan=fill>3?fill-3:1;
    }
    if(!stop) {
        if(slices){memset(au+au_size,0,AV_INPUT_BUFFER_PADDING_SIZE);decode(c,frame,au,au_size);}
        for(int i=0;i<32;i++){unsigned before=shared->decoded;decode(c,frame,0,0);if(shared->decoded==before)break;}
    }
    close(fd);
    fprintf(stderr,"QNX_NATIVE_DECODE_DONE decoded=%u errors=%u rendered=%u render_errors=%u\n",
            shared->decoded,shared->errors,shared->rendered,shared->render_errors);
    av_frame_free(&frame);avcodec_free_context(&c);free(buf);free(au);
    munmap(shared,sizeof(*shared));return 0;
}
