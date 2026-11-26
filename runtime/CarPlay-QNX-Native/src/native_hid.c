/* CarPlay HID report encoding inside the QNX guest.
 * The host forwards these exact bytes over its existing AirPlay event session.
 * No identity, pairing key or radio protocol state is stored here.
 * SPDX-License-Identifier: GPL-3.0-only
 */
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define KNOB_UID 0x2a2a2a2bU
#define TOUCH_UID 0x2a2a2a2aU
static unsigned width=1280, height=480;

static int integer(const char *s,long low,long high,long *out){
    char *end;long value;
    if(!s||!*s)return 0;
    errno=0;value=strtol(s,&end,10);
    if(errno||*end||value<low||value>high)return 0;
    *out=value;return 1;
}
static int coordinate(const char *s,unsigned max,unsigned *out){
    char *end;double value;
    if(!s||!*s)return 0;
    errno=0;value=strtod(s,&end);
    if(errno||*end||!isfinite(value))return 0;
    if(value<0)value=0;if(value>1)value=1;
    *out=(unsigned)floor(value*max+.5);return 1;
}
static void failure(long seq){printf("{\"seq\":%ld,\"ok\":false,\"error\":\"invalid HID command\"}\n",seq);}
static void report(unsigned uid,const unsigned char *bytes,unsigned count){
    unsigned i;printf("{\"uid\":%u,\"hex\":\"",uid);
    for(i=0;i<count;i++)printf("%02x",bytes[i]);printf("\"}");
}
static void begin(long seq){printf("{\"seq\":%ld,\"ok\":true,\"reports\":[",seq);}
static void finish(void){puts("]}");}
static void process(char *line){
    char *tokens[32],*save=0,*s;unsigned count=0,i;
    long seq=0,steps=0;unsigned char knob[4]={0},rest[4]={0},touch[12]={0};
    touch[6]=1;
    for(s=strtok_r(line," \t\r\n",&save);s;s=strtok_r(0," \t\r\n",&save)){
        if(count==32){failure(0);return;}tokens[count++]=s;
    }
    if(count<2||!integer(tokens[1],1,INT_MAX,&seq)){failure(0);return;}
    if(!strcmp(tokens[0],"R")&&count==2){
        begin(seq);report(KNOB_UID,rest,4);putchar(',');report(TOUCH_UID,touch,12);finish();return;
    }
    if(!strcmp(tokens[0],"A")){
        if(count!=4||!integer(tokens[3],-16,16,&steps)){failure(seq);return;}
        s=tokens[2];
        if(!strcmp(s,"rotate")){if(!steps){failure(seq);return;}knob[3]=(unsigned char)(signed char)steps;}
        else if(steps){failure(seq);return;}
        else if(!strcmp(s,"up"))knob[3]=255;
        else if(!strcmp(s,"down"))knob[3]=1;
        else if(!strcmp(s,"tilt_left"))knob[1]=129;
        else if(!strcmp(s,"tilt_right"))knob[1]=127;
        else if(!strcmp(s,"tilt_up"))knob[2]=129;
        else if(!strcmp(s,"tilt_down"))knob[2]=127;
        else if(!strcmp(s,"select"))knob[0]=1;
        else if(!strcmp(s,"menu"))knob[0]=2;
        else if(!strcmp(s,"back"))knob[0]=4;
        else{failure(seq);return;}
        begin(seq);report(KNOB_UID,knob,4);putchar(',');report(KNOB_UID,rest,4);finish();return;
    }
    if(!strcmp(tokens[0],"T")){
        long contacts,id,down;unsigned seen=0,x,y;
        if(count<3||!integer(tokens[2],0,2,&contacts)||count!=3+4*(unsigned)contacts){failure(seq);return;}
        for(i=0;i<(unsigned)contacts;i++){
            unsigned at=3+4*i,offset;
            if(!integer(tokens[at],0,1,&id)||!coordinate(tokens[at+1],width,&x)||
               !coordinate(tokens[at+2],height,&y)||!integer(tokens[at+3],0,1,&down)||
               (seen&(1U<<id))){failure(seq);return;}
            seen|=1U<<id;offset=(unsigned)id*6;
            touch[offset+1]=(unsigned char)down;
            touch[offset+2]=x&255;touch[offset+3]=x>>8;
            touch[offset+4]=y&255;touch[offset+5]=y>>8;
        }
        begin(seq);report(TOUCH_UID,touch,12);finish();return;
    }
    failure(seq);
}
int main(int argc,char **argv){
    char line[1024];long w,h;
    if(argc!=3||!integer(argv[1],2,65535,&w)||!integer(argv[2],2,65535,&h))return 2;
    width=(unsigned)w;height=(unsigned)h;setvbuf(stdout,0,_IOLBF,0);
#ifdef __QNXNTO__
    printf("{\"type\":\"ready\",\"platform\":\"QNX\",\"pid\":%ld,\"width\":%u,\"height\":%u}\n",(long)getpid(),width,height);
#else
    puts("{\"type\":\"ready\",\"platform\":\"host-test\"}");
#endif
    while(fgets(line,sizeof(line),stdin)){
        if(!strchr(line,'\n')){int c;while((c=getchar())!='\n'&&c!=EOF){}failure(0);continue;}
        process(line);
    }
    return ferror(stdin)?1:0;
}
