#include <time.h>
#define GL_SILENCE_DEPRECATION 1
#include <GLUT/glut.h>
#include <OpenGL/gl.h>
#include <OpenGL/glext.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <strings.h>
#include "glops.h"
#include <OpenGL/OpenGL.h>
typedef unsigned int u32;
static const char *SOCK="/tmp/glbridge.sock";
static const char *CTL="/tmp"; static char pbuf_[8][512]; static int pidx_;
static const char *P(const char*n){ char*b=pbuf_[pidx_++&7]; snprintf(b,512,"%s/%s",CTL,n); return b; }
static int verbose, nogl;
static u32 *maps[5]; static u32 mapcap[5];
static GLuint screen_fbo, screen_tex, screen_rb; static int sw=1920, sh=720;
static GLuint cur_arr, cur_elem, scratch_vbo[16], scratch_ebo;
static u32 rb_ds[65536];
static int winw=1440,winh=710, glready;
static inline float F(u32 x){ union{u32 u;float f;}c; c.u=x; return c.f; }
#define MAPMAX (1u<<22)   /* ids do guest acima disso (ou classe fora de 0..4) seriam memória corrompida ou laço infinito em setmap */
static void setmap(int cls,u32 gid,u32 hid){
  if(cls<0||cls>=5||gid>=MAPMAX) return;
  if(gid>=mapcap[cls]){ u32 nc=mapcap[cls]?mapcap[cls]:4096; while(nc<=gid) nc*=2; maps[cls]=realloc(maps[cls],nc*4); memset(maps[cls]+mapcap[cls],0,(nc-mapcap[cls])*4); mapcap[cls]=nc; }
  maps[cls][gid]=hid; }
static GLuint H(int cls,u32 gid){ if(cls<0||cls>=5) return 0; if(cls==2&&gid==0) return screen_fbo; if(!gid) return 0; if(gid>=mapcap[cls]) return 0; return maps[cls][gid]; }
static void ensure_screen(int w,int h){
  if(screen_fbo&&w==sw&&h==sh) return;
  if(!screen_fbo){ glGenFramebuffersEXT(1,&screen_fbo); glGenTextures(1,&screen_tex); glGenRenderbuffersEXT(1,&screen_rb); }
  sw=w; sh=h;
  glBindTexture(GL_TEXTURE_2D,screen_tex); glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,0);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR);
  glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);
  glBindRenderbufferEXT(GL_RENDERBUFFER_EXT,screen_rb); glRenderbufferStorageEXT(GL_RENDERBUFFER_EXT,GL_DEPTH24_STENCIL8_EXT,w,h);
  glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,screen_fbo);
  glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,screen_tex,0);
  glFramebufferRenderbufferEXT(GL_FRAMEBUFFER_EXT,GL_DEPTH_ATTACHMENT_EXT,GL_RENDERBUFFER_EXT,screen_rb);
  glFramebufferRenderbufferEXT(GL_FRAMEBUFFER_EXT,GL_STENCIL_ATTACHMENT_EXT,GL_RENDERBUFFER_EXT,screen_rb);
  glViewport(0,0,w,h); glScissor(0,0,w,h);
  glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT);
  fprintf(stderr,"[host] screen fbo %dx%d status=0x%x\n",w,h,glCheckFramebufferStatusEXT(GL_FRAMEBUFFER_EXT));
}
static void dump_stats(void);
static void draw_panel(void);
static void shot(void){ if(access(P("glshot.req"),F_OK)) return; unlink(P("glshot.req")); dump_stats();
  unsigned char *b=malloc(sw*sh*3); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,screen_fbo); glPixelStorei(GL_PACK_ALIGNMENT,1); glReadPixels(0,0,sw,sh,GL_RGB,GL_UNSIGNED_BYTE,b); glPixelStorei(GL_PACK_ALIGNMENT,4);
  FILE*f=fopen(P("glshot.ppm"),"wb"); fprintf(f,"P6\n%d %d\n255\n",sw,sh); for(int y=sh-1;y>=0;y--) fwrite(b+y*sw*3,1,sw*3,f); fclose(f); free(b); fprintf(stderr,"[host] screenshot saved\n"); }
#include <sys/mman.h>
#include <fcntl.h>
static unsigned char *fmap; static size_t fmaplen; static double fexp_t; static int fdirty;
static int map_readback(unsigned char *out); static GLuint map_present_tex(void);
static void export_frame(void){ if(!fmap) return; fdirty=1; struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts); double t=ts.tv_sec+ts.tv_nsec*1e-9; if(t-fexp_t<0.033) return; fexp_t=t; fdirty=0; GLint sfbo; glGetIntegerv(GL_FRAMEBUFFER_BINDING_EXT,&sfbo);
  size_t need=32+(size_t)sw*sh*3; if(need>fmaplen) return; static unsigned char *tmp; static size_t tcap; if(tcap<(size_t)sw*sh*3){ tcap=(size_t)sw*sh*3; tmp=realloc(tmp,tcap); }
  if(!map_readback(tmp)){ GLint pbo=0,rl=0,sr=0,sp=0; glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&pbo); glGetIntegerv(GL_PACK_ROW_LENGTH,&rl); glGetIntegerv(GL_PACK_SKIP_ROWS,&sr); glGetIntegerv(GL_PACK_SKIP_PIXELS,&sp);
    glBindBuffer(GL_PIXEL_PACK_BUFFER,0); glPixelStorei(GL_PACK_ROW_LENGTH,0); glPixelStorei(GL_PACK_SKIP_ROWS,0); glPixelStorei(GL_PACK_SKIP_PIXELS,0);   /* estado do guest não pode estourar tmp */
    glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,screen_fbo); glPixelStorei(GL_PACK_ALIGNMENT,1); glReadPixels(0,0,sw,sh,GL_RGB,GL_UNSIGNED_BYTE,tmp); glPixelStorei(GL_PACK_ALIGNMENT,4);
    glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo); glPixelStorei(GL_PACK_ROW_LENGTH,rl); glPixelStorei(GL_PACK_SKIP_ROWS,sr); glPixelStorei(GL_PACK_SKIP_PIXELS,sp); }
  unsigned *h=(unsigned*)fmap; h[4]=h[1]+1; __sync_synchronize();   /* [4] = quadro em escrita, [1] = último completo: o leitor descarta cópias rasgadas */
  for(int y=0;y<sh;y++) memcpy(fmap+32+(size_t)y*sw*3,tmp+(size_t)(sh-1-y)*sw*3,(size_t)sw*3);
  h[0]=0x52464449; h[2]=sw; h[3]=sh; __sync_synchronize(); h[1]++; glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,sfbo); }
static int window_shown;
static void present(void){
  if(!window_shown){ if(access(P("glshot.req"),F_OK)==0||fmap){ GLint fbo; glGetIntegerv(GL_FRAMEBUFFER_BINDING_EXT,&fbo); shot(); export_frame(); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fbo); } return; }
  GLint prog,fbo,rbo,tex,at,arr; glGetIntegerv(GL_CURRENT_PROGRAM,&prog); glGetIntegerv(GL_FRAMEBUFFER_BINDING_EXT,&fbo);
  glGetIntegerv(GL_RENDERBUFFER_BINDING_EXT,&rbo); glGetIntegerv(GL_ARRAY_BUFFER_BINDING,&arr);
  glPushAttrib(GL_ALL_ATTRIB_BITS); glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS);
  glUseProgram(0); shot(); export_frame(); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,0);
  winw=glutGet(GLUT_WINDOW_WIDTH); winh=glutGet(GLUT_WINDOW_HEIGHT);
  { int shh=(int)((float)winw*sh/sw); glViewport(0,winh-shh,winw,shh); } glDisable(GL_SCISSOR_TEST); glDisable(GL_BLEND); glDisable(GL_DEPTH_TEST); glDisable(GL_STENCIL_TEST); glDisable(GL_CULL_FACE);
  glColorMask(1,1,1,1); glActiveTexture(GL_TEXTURE0); glEnable(GL_TEXTURE_2D); glBindTexture(GL_TEXTURE_2D,map_present_tex());
  glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity(); glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity();
  glColor4f(1,1,1,1);
  glBegin(GL_QUADS); glTexCoord2f(0,0); glVertex2f(-1,-1); glTexCoord2f(1,0); glVertex2f(1,-1); glTexCoord2f(1,1); glVertex2f(1,1); glTexCoord2f(0,1); glVertex2f(-1,1); glEnd();
  glMatrixMode(GL_PROJECTION); glPopMatrix(); glMatrixMode(GL_MODELVIEW); glPopMatrix();
  glViewport(0,0,winw,winh); draw_panel();
  glutSwapBuffers();
  glPopClientAttrib(); glPopAttrib(); glUseProgram(prog); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fbo); glBindRenderbufferEXT(GL_RENDERBUFFER_EXT,rbo); glBindBuffer(GL_ARRAY_BUFFER,arr);
}
static void do_bindbuffer(u32 t,GLuint id){ if(t==GL_ARRAY_BUFFER) cur_arr=id; else if(t==GL_ELEMENT_ARRAY_BUFFER) cur_elem=id; glBindBuffer(t,id); }
#define TEXT(t) ((t)==0x8D65?GL_TEXTURE_2D:(t))   /* GL_TEXTURE_EXTERNAL_OES (textura de superficie redirecionada) e uma textura comum aqui */
static void do_texparam(u32 t,u32 pn,int v){ if(pn==0x84FE||pn==0x84FF) return; glTexParameteri(TEXT(t),pn,v); }
static u32 mapfmt(u32 f){ switch(f){ case 0x81A5:case 0x8D48:case 0x81A6: return GL_DEPTH24_STENCIL8_EXT; case 0x8056:case 0x8057: return GL_RGBA8; case 0x8D62: return GL_RGB8; } return f; }
static void rb_storage(u32 t,u32 f,u32 w,u32 h){ GLint cur; glGetIntegerv(GL_RENDERBUFFER_BINDING_EXT,&cur); u32 nf=mapfmt(f); if(cur<65536) rb_ds[cur]=(nf==GL_DEPTH24_STENCIL8_EXT); glRenderbufferStorageEXT(t,nf,w,h); }
static void fb_renderbuffer(u32 t,u32 att,u32 rbt,u32 rb){
  GLuint h=H(3,rb);
  if(att==0x8D00||att==0x8D20){ if(h&&h<65536&&rb_ds[h]){ glFramebufferRenderbufferEXT(t,0x8D00,rbt,h); glFramebufferRenderbufferEXT(t,0x8D20,rbt,h); } else { glFramebufferRenderbufferEXT(t,0x8D00,rbt,h); glFramebufferRenderbufferEXT(t,0x8D20,rbt,h); } }
  else glFramebufferRenderbufferEXT(t,att,rbt,h); }
static char *es2gl(const char*src,u32 n,int *outlen){
  char *o=malloc(n+512); int k=0; const char *hd="#version 120\n#define highp\n#define mediump\n#define lowp\n#define samplerExternalOES sampler2D\n"; k=sprintf(o,"%s",hd);
  u32 i=0; while(i<n){ u32 e=i; while(e<n&&src[e]!='\n') e++; const char*ln=src+i; u32 l=e-i; u32 b=0; while(b<l&&(ln[b]==' '||ln[b]=='\t')) b++;
    int drop=0; if(l-b>=8&&!strncmp(ln+b,"#version",8)) drop=1; if(l-b>=10&&!strncmp(ln+b,"#extension",10)) drop=1;
    if(l-b>=9&&!strncmp(ln+b,"precision",9)&&(ln[b+9]==' '||ln[b+9]=='\t')) drop=1;
    if(!drop){ memcpy(o+k,ln,l); k+=l; } o[k++]='\n'; i=e+1; }
  o[k]=0; *outlen=k; return o; }
#include "shgen.c"
/* debug: P("glskip") holds a shader-name substring whose draws are dropped; P("gldraws.req") logs the next draws */
static int probe_x=-1,probe_y,probe_n,probe_pending; static unsigned char probe_last[4];
static void probe_after(void){ unsigned char c[4]; glReadPixels(probe_x,probe_y,1,1,GL_RGBA,GL_UNSIGNED_BYTE,c); if(memcmp(c,probe_last,4)){ GLint p=0,sf=0,df=0,en=0; glGetIntegerv(GL_CURRENT_PROGRAM,&p); glGetIntegerv(GL_BLEND_SRC_RGB,&sf); glGetIntegerv(GL_BLEND_DST_RGB,&df); en=glIsEnabled(GL_BLEND); fprintf(stderr,"[probe] (%d,%d,%d,%d)->(%d,%d,%d,%d) blend=%d %x %x %s\n",probe_last[0],probe_last[1],probe_last[2],probe_last[3],c[0],c[1],c[2],c[3],en,sf,df,shname(hostprog_name[p&65535][1])); memcpy(probe_last,c,4); } }
static char skipstr[128]; static int drawlog; static int draw_ok(void){ GLint p=0; glGetIntegerv(GL_CURRENT_PROGRAM,&p); if(probe_n>0&&time(0)<probe_n) probe_pending=1; if(p<=0||p>=65536) return 1; const char*n=shname(hostprog_name[p][1]); if(drawlog>0){ drawlog--; fprintf(stderr,"[draw] %d %s\n",p,n); } return !(skipstr[0]&&strstr(n,skipstr)); }
static void poll_dbg(void){ static int c; if(++c%16) return; { FILE*pf=fopen(P("glprobe"),"r"); if(pf){ if(fscanf(pf,"%d %d",&probe_x,&probe_y)==2){ probe_n=time(0)+4; memset(probe_last,0,4); fprintf(stderr,"[probe] start %d %d\n",probe_x,probe_y); } fclose(pf); unlink(P("glprobe")); } } FILE*f=fopen(P("glskip"),"r"); skipstr[0]=0; if(f){ if(fgets(skipstr,127,f)){ char*e=strchr(skipstr,10); if(e)*e=0; } fclose(f); } if(!access(P("gldraws.req"),F_OK)){ unlink(P("gldraws.req")); drawlog=400; } }
static u32 drawcnt[MAXSH]; static u32 prog_of_host[MAXSH]; 
static void count_draw(void){ GLint p=0; glGetIntegerv(GL_CURRENT_PROGRAM,&p); if(p>=0&&p<MAXSH) drawcnt[p]++; }
static void do_compile(u32 gid){ GLuint s=H(4,gid); glCompileShader(s); GLint ok=0; glGetShaderiv(s,GL_COMPILE_STATUS,&ok);
  if(!ok){ char log[4096]; GLint l=0; glGetShaderInfoLog(s,4096,&l,log); fprintf(stderr,"[host] SHADER COMPILE FAILED (guest %u): %s\n",gid,log); } }
static void on_mouse(int,int,int,int); static void on_motion(int,int); static void on_key(unsigned char,int,int); static void on_keyup(unsigned char,int,int); static void on_special(int,int,int);
static int gltrace; static u32 nswaps;
static u32 inq[1024*4]; static u32 inq_n;
static void input_ev(u32 type,u32 code,u32 val,u32 unit){ if(inq_n>=1024) return; u32*e=inq+inq_n*4; e[0]=type;e[1]=code;e[2]=val;e[3]=unit; inq_n++; }
static void map_cmd(const char *l);
static void input_line(const char *l){ u32 t,c,v,u=0xffff; if((l[0]=='M'||l[0]=='V')&&l[1]==' '){ map_cmd(l); return; } if(sscanf(l,"%u %u %d %u",&t,&c,(int*)&v,&u)>=3){ if(t==100) on_mouse(GLUT_LEFT_BUTTON,GLUT_DOWN,c,v); else if(t==101) on_mouse(GLUT_LEFT_BUTTON,GLUT_UP,c,v); else if(t==102) on_motion(c,v); else if(t==103) on_key((unsigned char)c,0,0); else if(t==104) on_keyup((unsigned char)c,0,0); else if(t==105) on_special(c,0,0); else input_ev(t,c,v,u); } }
/* entrada por socket de datagramas (<ctl>/input.sock): com o arquivo glinput.cmd, um evento escrito entre a leitura e o unlink se perdia (teclas "sumiam") */
static int ifd=-1;
static void poll_cmdfile(void){ if(ifd>=0){ char l[128]; ssize_t n; while((n=recv(ifd,l,sizeof l-1,MSG_DONTWAIT))>0){ l[n]=0; input_line(l); } } if(access(P("glinput.cmd"),F_OK)) return; FILE*f=fopen(P("glinput.cmd"),"r"); if(!f) return; char l[128]; while(fgets(l,128,f)) input_line(l); fclose(f); unlink(P("glinput.cmd")); }
#include "panel.c"
static u32 *rp; static u32 rl;   /* reply words */
static u32 repbuf[(8<<20)/4];
static void reply_u32(u32 v){ rp=repbuf; rp[0]=v; rl=4; }
static void reply_bytes(const void*d,u32 n){ rp=repbuf; memcpy(rp,d,n); rl=n; }
static void dump_stats(void){ fprintf(stderr,"[host] total swaps %u\n",nswaps); for(int i=0;i<65536;i++) if(drawcnt[i]) fprintf(stderr,"[host] DRAWS %u prog=%d vs=%s fs=%s\n",drawcnt[i],i,shname(hostprog_name[i][0]),shname(hostprog_name[i][1])); }
/* Boot rápido: GLHOST_RECORD grava toda requisição que muda o estado GL desde o início do guest; GLHOST_REPLAY reexecuta a gravação antes de aceitar o guest restaurado de um snapshot do QEMU
   (o estado GL vive aqui, fora do guest, e não vai no snapshot). <ctl>/glrec.stop encerra a gravação e cria <ctl>/glrec.done. */
static FILE *recf; static int replaying; static long long glog_bytes; static long long glog_max=64LL<<20;
#include "map.c"
static void rec_write(u32 *w,u32 n){ if(!recf) return; if(n>=8&&(w[0]==OP_GETINPUT||w[0]==OP_LOG)&&(n/4==2+w[1])) return; fwrite(&n,4,1,recf); fwrite(w,1,n,recf); }
static void rec_poll(void){ if(!recf||access(P("glrec.stop"),F_OK)) return; unlink(P("glrec.stop")); fflush(recf); fclose(recf); recf=0; FILE*f=fopen(P("glrec.done"),"w"); if(f) fclose(f); fprintf(stderr,"[host] gravacao GL encerrada\n"); }
static const char *opname[]={
#include "opnames.inc"
};
static void process(u32 *w,u32 nbytes){
  u32 *end=w+nbytes/4; rl=0; rp=repbuf;
  while(w+2<=end){
    u32 op=w[0],n=w[1]; u32 *a=w+2;
    if(n>(u32)(end-w-2)){ fprintf(stderr,"[host] truncated cmd op=%u\n",op); break; }   /* antes de somar: 2+n em 32 bits dava a volta e o laço não terminava */
    w+=2+n;
    if(probe_pending){ probe_pending=0; probe_after(); }
    if(gltrace>0&&op!=OP_LOG&&op!=OP_GETINPUT){ gltrace--; fprintf(stderr,"[gl] %s %x %x %x %x\n",op<sizeof opname/sizeof opname[0]?opname[op]:"?",n>0?a[0]:0,n>1?a[1]:0,n>2?a[2]:0,n>3?a[3]:0); }
    if(nogl&&op!=OP_LOG&&op!=OP_SWAP){ continue; }
    switch(op){
#include "gen_host.inc"
    case OP_GEN:{ u32 cls=a[0],cnt=a[1],i; if(n<2||cls>=5) break; if(cnt>n-2) cnt=n-2; for(i=0;i<cnt;i++){ GLuint h=0; if(cls==0) glGenTextures(1,&h); else if(cls==1) glGenBuffers(1,&h); else if(cls==2) glGenFramebuffersEXT(1,&h); else glGenRenderbuffersEXT(1,&h); setmap(cls,a[2+i],h); } break; }
    case OP_MAPBIND: map_bind(a[0],a[1],a[2]); break;
    case OP_MAPLAYER: map_set_layer(a[0],a[1],a[2],a[3],a[4]); break;
    case OP_VIDLAYER: vid_set_layer(a[0],a[1],a[2],a[3],a[4]); break;
    case OP_DEL:{ u32 cls=a[0],cnt=a[1],i; if(n<2||cls>=5) break; if(cnt>n-2) cnt=n-2; for(i=0;i<cnt;i++){ GLuint h=H(cls,a[2+i]); if(!h) continue; if(cls==0){ map_forget(h); glDeleteTextures(1,&h); } else if(cls==1) glDeleteBuffers(1,&h); else if(cls==2) glDeleteFramebuffersEXT(1,&h); else if(cls==3) glDeleteRenderbuffersEXT(1,&h); else { if(glIsShader(h)) glDeleteShader(h); else glDeleteProgram(h);} setmap(cls,a[2+i],0); } break; }
    case OP_CREATESHADER: setmap(4,a[0],glCreateShader(a[1])); break;
    case OP_CREATEPROGRAM: setmap(4,a[0],glCreateProgram()); break;
    case OP_BUFFERDATA: glBufferData(a[0],a[1],NULL,a[2]); break;
    case OP_BUFFERSUBDATA: glBufferSubData(a[0],a[1],a[2],a+3); break;
    case OP_TEXIMAGE:{ u32 ifmt=a[2]; if(alpha_hack&&a[6]==GL_ALPHA&&a[7]==GL_UNSIGNED_BYTE){ u32 cnt=a[3]*a[4]; unsigned char*rgba=NULL; if(a[8]){ rgba=malloc(cnt*4); unsigned char*sr=(unsigned char*)(a+10); { GLint al=4; glGetIntegerv(GL_UNPACK_ALIGNMENT,&al); u32 row=(a[3]+al-1)/al*al; for(u32 y=0;y<a[4];y++) for(u32 x=0;x<a[3];x++){ u32 i=y*a[3]+x; rgba[i*4]=rgba[i*4+1]=rgba[i*4+2]=255; rgba[i*4+3]=sr[y*row+x]; } } } glTexImage2D(a[0],a[1],GL_RGBA,a[3],a[4],0,GL_RGBA,GL_UNSIGNED_BYTE,rgba); free(rgba); break; } if(ifmt==0x80E1) ifmt=GL_RGBA; glTexImage2D(a[0],a[1],ifmt,a[3],a[4],0,a[6]==0x80E1&&0?GL_BGRA:a[6],a[7],a[8]?(void*)(a+10):NULL); break; }
    case OP_TEXSUBIMAGE: if(alpha_hack&&a[6]==GL_ALPHA&&a[7]==GL_UNSIGNED_BYTE){ u32 cnt=a[4]*a[5]; unsigned char*rgba=malloc(cnt*4+4); unsigned char*sr=(unsigned char*)(a+9); { GLint al=4; glGetIntegerv(GL_UNPACK_ALIGNMENT,&al); u32 row=(a[4]+al-1)/al*al; for(u32 y=0;y<a[5];y++) for(u32 x=0;x<a[4];x++){ u32 i=y*a[4]+x; rgba[i*4]=rgba[i*4+1]=rgba[i*4+2]=255; rgba[i*4+3]=sr[y*row+x]; } } glTexSubImage2D(a[0],a[1],a[2],a[3],a[4],a[5],GL_RGBA,GL_UNSIGNED_BYTE,rgba); free(rgba); break; } glTexSubImage2D(a[0],a[1],a[2],a[3],a[4],a[5],a[6],a[7],(void*)(a+9)); break;
    case OP_GETINPUT:{ u32 n=inq_n>64?64:inq_n; memcpy(repbuf,inq,n*16); memmove(inq,inq+n*4,(inq_n-n)*16); inq_n-=n; rp=repbuf; rl=n*16; break; }
    case OP_SHADERBIN:{ u32 g=a[0]; if(g<MAXSH){ ShInfo*si=calloc(1,sizeof(ShInfo)); if(parse_syms((unsigned char*)(a+2),a[1],si)){ si->hash=fnv1a((unsigned char*)(a+2),a[1]); free(shinfo[g]); shinfo[g]=si; } else { free(si); fprintf(stderr,"[host] shader binary parse failed gid=%u len=%u\n",g,a[1]); si=calloc(1,sizeof(ShInfo)); si->kind=((unsigned char*)(a+2))[0x23]; shinfo[g]=si; } } break; }
    case OP_SHADERSOURCE:{ int l; char*s=es2gl((char*)(a+2),a[1],&l); const char*p=s; GLint len=l; glShaderSource(H(4,a[0]),1,&p,&len); free(s); break; }
    case OP_UNIFORMV:{ u32 loc=a[0],c=a[1],v=a[2],isi=a[3]; const void*d=a+4;
      if(isi){ switch(v){case 1:glUniform1iv(loc,c,d);break;case 2:glUniform2iv(loc,c,d);break;case 3:glUniform3iv(loc,c,d);break;default:glUniform4iv(loc,c,d);} }
      else { switch(v){case 1:glUniform1fv(loc,c,d);break;case 2:glUniform2fv(loc,c,d);break;case 3:glUniform3fv(loc,c,d);break;default:glUniform4fv(loc,c,d);} } break; }
    case OP_UNIFORMMATRIX:{ u32 loc=a[0],c=a[1],dim=a[2],tr=a[3]; const float*d=(float*)(a+4); if(dim==2)glUniformMatrix2fv(loc,c,tr,d); else if(dim==3)glUniformMatrix3fv(loc,c,tr,d); else glUniformMatrix4fv(loc,c,tr,d); break; }
    case OP_ATTRIBPTR: glVertexAttribPointer(a[0],a[1],a[2],a[3],a[4],(void*)(unsigned long)a[5]); break;
    case OP_CLIENTATTRIB:{ u32 i=a[0]; if(i>=16) break; if(!scratch_vbo[i]) glGenBuffers(1,&scratch_vbo[i]);
      glBindBuffer(GL_ARRAY_BUFFER,scratch_vbo[i]); glBufferData(GL_ARRAY_BUFFER,a[5],a+7,GL_STREAM_DRAW); glVertexAttribPointer(i,a[1],a[2],a[3],a[4],(void*)0); glBindBuffer(GL_ARRAY_BUFFER,cur_arr); break; }
    case OP_DRAWARRAYS: count_draw(); if(draw_ok()) glDrawArrays(a[0],a[1],a[2]); break;
    case OP_DRAWELEMENTS:{ count_draw(); if(!draw_ok()) break; if(a[3]){ if(!scratch_ebo) glGenBuffers(1,&scratch_ebo); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,scratch_ebo); glBufferData(GL_ELEMENT_ARRAY_BUFFER,a[4],a+5,GL_STREAM_DRAW); glDrawElements(a[0],a[1],a[2],(void*)0); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER,cur_elem); }
      else glDrawElements(a[0],a[1],a[2],(void*)(unsigned long)a[4]); break; }
    case OP_GETUNILOC:{ char nm[256]; u32 l=a[1]; if(l>255)l=255; memcpy(nm,a+2,l); nm[l]=0; reply_u32(glGetUniformLocation(H(4,a[0]),gname(nm))); break; }
    case OP_GETATTRLOC:{ char nm[256]; u32 l=a[1]; if(l>255)l=255; memcpy(nm,a+2,l); nm[l]=0; reply_u32(glGetAttribLocation(H(4,a[0]),nm)); break; }
    case OP_GETSHADERIV:{ GLint v=0; if(a[0]<MAXSH&&shinfo[a[0]]) v=(a[1]==GL_COMPILE_STATUS); else glGetShaderiv(H(4,a[0]),a[1],&v); reply_u32(v); break; }
    case OP_GETPROGRAMIV:{ GLint v=0; glGetProgramiv(H(4,a[0]),a[1],&v); reply_u32(v); break; }
    case OP_SHADERLOG:{ static char lg[8192]; GLint l=0; glGetShaderInfoLog(H(4,a[0]),8192,&l,lg); reply_bytes(lg,l); break; }
    case OP_PROGRAMLOG:{ static char lg[8192]; GLint l=0; glGetProgramInfoLog(H(4,a[0]),8192,&l,lg); reply_bytes(lg,l); break; }
    case OP_GETACTIVE:{ char nm[256]; GLsizei l=0; GLint sz=0; GLenum ty=0; if(a[0]==0) glGetActiveAttrib(H(4,a[1]),a[2],256,&l,&sz,&ty,nm); else glGetActiveUniform(H(4,a[1]),a[2],256,&l,&sz,&ty,nm);
      u32 *r=repbuf; r[0]=sz; r[1]=ty; r[2]=0; memcpy(r+3,nm,l); rp=repbuf; rl=12+l; break; }
    case OP_GETINTEGERV:{ u32 r[16]; memset(r,0,sizeof r); if(a[1]==0){ GLint v[16]={0}; glGetIntegerv(a[0],v); memcpy(r,v,sizeof v);} else if(a[1]==1){ GLfloat v[16]={0}; glGetFloatv(a[0],v); memcpy(r,v,sizeof v);} else { GLboolean v[16]={0}; glGetBooleanv(a[0],v); for(int i=0;i<16;i++) r[i]=v[i]; }
      reply_bytes(r,sizeof r); break; }
    case OP_READPIXELS:{ /* o buffer tem o tamanho que o GL escreve (até 4 bytes por pixel, com alinhamento), não o que o guest diz; a resposta cabe no repbuf */
      u32 row=a[6]; if(a[2]>8192||a[3]>8192){ reply_bytes(repbuf,0); break; }
      size_t sz=(size_t)row*a[3]; if(sz>sizeof repbuf) sz=sizeof repbuf;
      size_t gl=((size_t)a[2]*4+8)*a[3]+16; void *tmp=calloc(1,(sz>gl?sz:gl)+16);
      GLint pbo=0; glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING,&pbo); glBindBuffer(GL_PIXEL_PACK_BUFFER,0); glPixelStorei(GL_PACK_ROW_LENGTH,0); glPixelStorei(GL_PACK_SKIP_ROWS,0); glPixelStorei(GL_PACK_SKIP_PIXELS,0);
      glReadPixels(a[0],a[1],a[2],a[3],a[4],a[5],tmp); glBindBuffer(GL_PIXEL_PACK_BUFFER,pbo); reply_bytes(tmp,(u32)sz); free(tmp); break; }
    case OP_CHECKFB: reply_u32(glCheckFramebufferStatusEXT(a[0])); break;
    case OP_GETATTACHED:{ GLuint ids[32]; GLsizei c=0; u32 mx=a[1]>32?32:a[1]; glGetAttachedShaders(H(4,a[0]),mx,&c,ids); u32 r[34]; r[0]=c; for(int i=0;i<c;i++){ r[1+i]=0; for(u32 g=1;g<mapcap[4];g++) if(maps[4][g]==ids[i]){ r[1+i]=g; break; } } reply_bytes(r,4+4*c); break; }
    case OP_SWAP: screen_seen=1; panel_dirty=0; ensure_screen(a[0],a[1]); if(!nogl&&!replaying){ present(); } reply_u32(0); { static int nsw; nswaps=++nsw; if(nsw<5||nsw%100==0) fprintf(stderr,"[host] swap #%d\n",nsw); } break;
    case OP_LOG:{ if(replaying||glog_bytes>=glog_max) break; char s[512]; u32 l=a[0]; if(l>511) l=511; memcpy(s,a+4,l); s[l]=0; glog_bytes+=fprintf(stderr,"[guest] %s %x %x %x\n",s,a[1],a[2],a[3]); if(glog_bytes>=glog_max) fprintf(stderr,"[host] log do guest cortado em %lld MB (GLHOST_LOG_MB muda o limite)\n",glog_max>>20); break; }
    default: if(op>200||op==0) fprintf(stderr,"[host] unknown op %u\n",op); break;
    }
    if(verbose&&op<OP_GEN&&0) {}
  }
}
static int lfd=-1,cfd=-1; static u32 *reqbuf; static u32 reqcap;
static int rd(int fd,void*b,size_t n){ char*p=b; while(n){ ssize_t r=recv(fd,p,n,0); if(r<=0) return -1; p+=r; n-=r; } return 0; }
static int wr(int fd,const void*b,size_t n){ const char*p=b; while(n){ ssize_t r=send(fd,p,n,0); if(r<=0) return -1; p+=r; n-=r; } return 0; }
static int cfd_busy_guard(void){ return 0; }
static double now_s(void){ struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts); return ts.tv_sec+ts.tv_nsec*1e-9; }
static void idle(void){
  static double last_ctl; double t0=now_s();
  if(panel_dirty&&window_shown){ panel_dirty=0; if(!cfd_busy_guard()) present(); }
  if(t0-last_ctl>0.008){ last_ctl=t0; map_tick(t0); poll_cmdfile(); poll_dbg(); rec_poll(); if(fdirty) export_frame(); if(!access(P("gltrace.req"),F_OK)){ unlink(P("gltrace.req")); gltrace=1500; fprintf(stderr,"[host] gl trace on\n"); } { static int ctr; if(++ctr%32==0){ GLint fb; glGetIntegerv(GL_FRAMEBUFFER_BINDING_EXT,&fb); shot(); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fb); } } }
  /* o vCPU fica parado (com o BQL) até a resposta: enquanto houver pedidos, não volta ao laço do GLUT, que custa muito mais que o pedido */
  do {
    struct pollfd pf[2]; int n=0; pf[n].fd=lfd; pf[n].events=POLLIN; n++; if(cfd>=0){ pf[n].fd=cfd; pf[n].events=POLLIN; n++; }
    if(poll(pf,n,fdirty?1:4)<=0) return;
    if(pf[0].revents&POLLIN){ int f=accept(lfd,0,0); if(f>=0){ if(cfd>=0) close(cfd); cfd=f; fprintf(stderr,"[host] guest connected\n"); } }
    if(n>1&&(pf[1].revents&(POLLIN|POLLHUP))){
      u32 len; if(rd(cfd,&len,4)){ close(cfd); cfd=-1; fprintf(stderr,"[host] guest disconnected\n"); return; }
      if(len>(64u<<20)){ fprintf(stderr,"[host] request too large (%u)\n",len); close(cfd); cfd=-1; return; }
      if(len>reqcap){ reqcap=len+4096; reqbuf=realloc(reqbuf,reqcap); if(!reqbuf){ reqcap=0; close(cfd); cfd=-1; return; } }
      if(rd(cfd,reqbuf,len)){ close(cfd); cfd=-1; return; }
      rec_write(reqbuf,len); process(reqbuf,len);
      u32 rlen=rl; if(wr(cfd,&rlen,4)||wr(cfd,repbuf,rlen)){ close(cfd); cfd=-1; }
    }
  } while(now_s()-t0<0.008);
}
static int replay_file(const char *path){
  FILE *f=fopen(path,"rb"); if(!f){ perror(path); return -1; } double t0=now_s(); u32 len; long long total=0; u32 cnt=0; replaying=1; static char iob[1<<20]; setvbuf(f,iob,_IOFBF,sizeof iob);
  while(fread(&len,4,1,f)==1){ if(len>(64u<<20)) break; if(len>reqcap){ reqcap=len+4096; reqbuf=realloc(reqbuf,reqcap); } if(fread(reqbuf,1,len,f)!=len) break; process(reqbuf,len); total+=len; cnt++; }
  fclose(f); replaying=0; glFinish();
  if(fmap){ GLint fbo; glGetIntegerv(GL_FRAMEBUFFER_BINDING_EXT,&fbo); fexp_t=0; export_frame(); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,fbo); }
  fprintf(stderr,"[host] replay: %u pedidos, %lld MB em %.2f s\n",cnt,total>>20,now_s()-t0); return 0; }
static void display(void){ panel_dirty=1; }
static void reshape(int w,int h){ winw=w; winh=h; }
int main(int argc,char**argv){
  glutInit(&argc,argv); verbose=getenv("GLHOST_VERBOSE")!=NULL; nogl=getenv("GLHOST_NOGL")!=NULL;
  const char*sc=getenv("GLHOST_SOCK"); if(sc) SOCK=sc;
  if(getenv("GLHOST_CTL")) CTL=getenv("GLHOST_CTL");
  if(getenv("GLHOST_FRAME")){ int ff=open(getenv("GLHOST_FRAME"),O_RDWR|O_CREAT,0644); fmaplen=32+1440*540*3; if(ff>=0&&ftruncate(ff,fmaplen)==0){ fmap=mmap(0,fmaplen,PROT_READ|PROT_WRITE,MAP_SHARED,ff,0); if(fmap==MAP_FAILED) fmap=0; } }
  if(getenv("GLHOST_W")) winw=atoi(getenv("GLHOST_W")); if(getenv("GLHOST_H")) winh=atoi(getenv("GLHOST_H"));
  glutInitDisplayMode(GLUT_RGBA|GLUT_DOUBLE|GLUT_DEPTH|GLUT_STENCIL); glutInitWindowSize(winw,winh);
  glutCreateWindow("BMW iDrive 6 (QEMU OMAP5)"); glutDisplayFunc(display); glutReshapeFunc(reshape); glutIdleFunc(idle); glutMouseFunc(on_mouse); glutMotionFunc(on_motion); glutKeyboardFunc(on_key); glutKeyboardUpFunc(on_keyup); glutSpecialFunc(on_special); glutSpecialUpFunc(on_specialup); glutIgnoreKeyRepeat(1);
  fprintf(stderr,"[host] GL_VERSION=%s RENDERER=%s\n",glGetString(GL_VERSION),glGetString(GL_RENDERER));
  load_index(); ensure_screen(1440,540); window_shown=getenv("GLHOST_SHOW")!=NULL; if(!window_shown) glutHideWindow();
  { GLint si=0; CGLSetParameter(CGLGetCurrentContext(),kCGLCPSwapInterval,&si); }
  if(getenv("GLHOST_LOG_MB")) glog_max=atoll(getenv("GLHOST_LOG_MB"))<<20;
  if(getenv("GLHOST_REPLAY")&&replay_file(getenv("GLHOST_REPLAY"))) return 3;
  if(getenv("GLHOST_RECORD")){ recf=fopen(getenv("GLHOST_RECORD"),"wb"); if(recf){ static char rb[1<<20]; setvbuf(recf,rb,_IOFBF,sizeof rb); } }
  { struct sockaddr_un ia={.sun_family=AF_UNIX}; snprintf(ia.sun_path,sizeof ia.sun_path,"%s",P("input.sock")); unlink(ia.sun_path); ifd=socket(AF_UNIX,SOCK_DGRAM,0); if(ifd>=0&&bind(ifd,(struct sockaddr*)&ia,sizeof ia)){ close(ifd); ifd=-1; } if(ifd>=0){ int rb=256*1024; setsockopt(ifd,SOL_SOCKET,SO_RCVBUF,&rb,sizeof rb); } }
  unlink(SOCK); lfd=socket(AF_UNIX,SOCK_STREAM,0); struct sockaddr_un sa={.sun_family=AF_UNIX}; strncpy(sa.sun_path,SOCK,sizeof sa.sun_path-1);
  if(bind(lfd,(struct sockaddr*)&sa,sizeof sa)||listen(lfd,1)){ perror("bind"); return 1; }
  fprintf(stderr,"[host] listening on %s\n",SOCK);
  glutMainLoop(); return 0; }
