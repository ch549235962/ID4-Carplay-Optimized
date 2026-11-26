/* Inspect/control the QNX display adapter without reading screen pixels. */
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include "native_video.h"
int main(int argc,char **argv){
    const char *flag="/var/tmp/nbt-native/show-video";
    if(argc==2&&!strcmp(argv[1],"hide")){unlink(flag);return 0;}
    if(argc==2&&!strcmp(argv[1],"show")){int fd=open(flag,O_CREAT|O_WRONLY,0600);if(fd<0)return 2;close(fd);return 0;}
    int fd=shm_open(NV_PATH,O_RDONLY,0);if(fd<0){puts("{\"ready\":false}");return 0;}
    const struct nv_shared *s=mmap(0,sizeof(*s),PROT_READ,MAP_SHARED,fd,0);close(fd);
    if(s==MAP_FAILED)return 2;
    printf("{\"ready\":%s,\"decoded\":%u,\"errors\":%u,\"rendered\":%u,\"render_errors\":%u,\"visible\":%s}\n",
           s->magic==NV_MAGIC?"true":"false",s->decoded,s->errors,s->rendered,s->render_errors,access(flag,F_OK)?"false":"true");
    munmap((void*)s,sizeof(*s));return 0;
}
