#include "common.h"
extern const struct { const char*n; void*p; } gl_funcs[];
/* ---------- QNX screen (minimal) ---------- */
#define NPROP 128
typedef struct obj { void *pv[NPROP]; u32 kind; s32 iv[NPROP][4]; s32 set[NPROP]; void *ptr; u32 stride; void *buf0; u32 w,h; struct obj *buffer; } obj_t;
enum { K_CTX=1,K_WIN,K_BUF,K_PIX };
static obj_t *newobj(u32 k){ obj_t*o=(obj_t*)calloc(1,sizeof(obj_t)); o->kind=k; return o; }
static void L(const char*s,u32 a,u32 b,u32 c){ br_logx(s,a,b,c); }
int screen_create_context(void**c,int f){ *c=newobj(K_CTX); L("screen_create_context",f,0,0); return 0; }
int screen_destroy_context(void*c){ L("screen_destroy_context",0,0,0); return 0; }
int screen_create_window(void**w,void*ctx){ obj_t*o=newobj(K_WIN); o->w=1920; o->h=720; *w=o; L("screen_create_window",(u32)o,0,0); return 0; }
int screen_create_window_type(void**w,void*ctx,int type){
  extern int *__get_errno_ptr(void);
  /* shortcut: native Screen buffer posting is unsupported; implement it before accepting typed windows. */
  if(w) *w=NULL;
  L("screen_create_window_type: unsupported",type,0,0);
  *__get_errno_ptr()=89; /* QNX ENOSYS (not the host's errno value). */
  return -1;
}
int screen_destroy_window(void*w){ L("screen_destroy_window",(u32)w,0,0); return 0; }
int screen_create_window_buffers(void*w,int n){ L("screen_create_window_buffers",(u32)w,n,0); return 0; }
static int setiv(obj_t*o,u32 pn,const s32*v,u32 n,const char*nm){ u32 i; if(o->kind==K_WIN&&pn==5&&v){ o->w=v[0]; o->h=v[1]; } if(pn<NPROP){ for(i=0;i<n&&i<4;i++) o->iv[pn][i]=v[i]; o->set[pn]=n; }
  L(nm,(u32)o,pn,v?(u32)v[0]:0); if(o->kind==K_WIN&&n>=2&&(pn==0x20||pn==0x1d||pn==0x21)) {} return 0; }
int screen_set_window_property_iv(void*w,u32 pn,const s32*v){ return setiv((obj_t*)w,pn,v,4,"screen_set_window_property_iv"); }
int screen_set_window_property_cv(void*w,u32 pn,s32 len,const char*v){ L("screen_set_window_property_cv",(u32)w,pn,len); return 0; }
int screen_create_pixmap(void**p,void*ctx){ obj_t*o=newobj(K_PIX); *p=o; L("screen_create_pixmap",(u32)o,0,0); return 0; }
int screen_destroy_pixmap(void*p){ L("screen_destroy_pixmap",(u32)p,0,0); return 0; }
int screen_set_pixmap_property_iv(void*p,u32 pn,const s32*v){ return setiv((obj_t*)p,pn,v,4,"screen_set_pixmap_property_iv"); }
int screen_create_pixmap_buffer(void*p){ obj_t*o=(obj_t*)p; L("screen_create_pixmap_buffer",(u32)o,0,0); return 0; }
int screen_get_pixmap_property_pv(void*p,u32 pn,void**out){ obj_t*o=(obj_t*)p; L("screen_get_pixmap_property_pv",(u32)o,pn,0); *out=o->buffer; return 0; }
int screen_attach_pixmap_buffer(void*p,void*b){ L("screen_attach_pixmap_buffer",(u32)p,(u32)b,0); return 0; }
int screen_create_buffer(void**b){ *b=newobj(K_BUF); L("screen_create_buffer",(u32)*b,0,0); return 0; }
int screen_get_buffer_property_iv(void*b,u32 pn,s32*out){ obj_t*o=(obj_t*)b; u32 i; for(i=0;i<4;i++) out[i]=o->iv[pn<NPROP?pn:0][i]; L("screen_get_buffer_property_iv",(u32)b,pn,(u32)out[0]); return 0; }
int screen_get_buffer_property_pv(void*b,u32 pn,void**out){ obj_t*o=(obj_t*)b; L("screen_get_buffer_property_pv",(u32)b,pn,0); *out=o->ptr; return 0; }
int screen_set_buffer_property_iv(void*b,u32 pn,const s32*v){ return setiv((obj_t*)b,pn,v,4,"screen_set_buffer_property_iv"); }
int screen_set_buffer_property_llv(void*b,u32 pn,const void*v){ L("screen_set_buffer_property_llv",(u32)b,pn,0); return 0; }
int screen_set_buffer_property_pv(void*b,u32 pn,void*const*v){ obj_t*o=(obj_t*)b; L("screen_set_buffer_property_pv",(u32)b,pn,(u32)v[0]); o->ptr=v[0]; return 0; }
extern int usleep(unsigned);
int screen_flush_context(void*c,int f){ return 0; }
int screen_create_event(void**e){ *e=newobj(K_BUF); L("screen_create_event",(u32)*e,0,0); return 0; }
int screen_destroy_event(void*e){ return 0; }
int screen_get_event(void*c,void*e,u64 timeout){ usleep(timeout&&timeout<20000000ULL?timeout/1000:20000); ((obj_t*)e)->iv[0][0]=0; return 0; }
int screen_send_event(void*c,void*e,int pid){ L("screen_send_event",pid,0,0); return 0; }
int screen_get_event_property_iv(void*e,u32 pn,s32*out){ obj_t*o=(obj_t*)e; u32 i; for(i=0;i<4;i++) out[i]=0; L("screen_get_event_property_iv",pn,0,0); return 0; }
int screen_get_event_property_pv(void*e,u32 pn,void**out){ *out=0; L("screen_get_event_property_pv",pn,0,0); return 0; }
int screen_set_event_property_iv(void*e,u32 pn,const s32*v){ L("screen_set_event_property_iv",pn,v?v[0]:0,0); return 0; }
int screen_get_window_property_iv(void*w,u32 pn,s32*out){ obj_t*o=(obj_t*)w; u32 i; for(i=0;i<4;i++) out[i]=(pn<NPROP&&o->set[pn])?o->iv[pn][i]:0; L("screen_get_window_property_iv",pn,(u32)out[0],(u32)out[1]); return 0; }
int screen_get_window_property_pv(void*w,u32 pn,void**out){ obj_t*o=(obj_t*)w; *out=pn<NPROP?o->pv[pn]:0; L("screen_get_window_property_pv",pn,(u32)*out,0); return 0; }
int screen_set_window_property_pv(void*w,u32 pn,void*const*v){ obj_t*o=(obj_t*)w; if(pn<NPROP) o->pv[pn]=v[0]; L("screen_set_window_property_pv",pn,(u32)v[0],0); return 0; }
int screen_get_window_property_cv(void*w,u32 pn,s32 len,char*out){ if(len>0) out[0]=0; L("screen_get_window_property_cv",pn,len,0); return 0; }
u32 eglGetConfigAttrib(void*d,void*cfg,s32 a,s32*v){ s32 r=0; switch(a){ case 0x3033:r=4;break; case 0x3024:case 0x3023:case 0x3022:case 0x3021:r=8;break; case 0x3025:r=24;break; case 0x3026:r=8;break; case 0x3040:case 0x3042:r=4;break; case 0x3020:r=32;break; case 0x3028:r=1;break; case 0x302E:r=0xe;break; case 0x3027:r=0x3038;break; case 0x3009:r=0;break; case 0x3003:r=0x3038;break; case 0x3031:r=0;break; case 0x3032:r=0;break; } if(v)*v=r; L("eglGetConfigAttrib",a,r,0); return 1; }
/* ---------- EGL ---------- */
static u32 egl_ctr=0x100;
void *eglGetDisplay(void*n){ L("eglGetDisplay",(u32)n,0,0); return (void*)1; }
u32 eglInitialize(void*d,s32*maj,s32*min){ L("eglInitialize",0,0,0); if(maj)*maj=1; if(min)*min=4; return 1; }
u32 eglChooseConfig(void*d,const s32*attr,void**cfgs,s32 sz,s32*num){ u32 i=0; L("eglChooseConfig",0,0,0); if(attr) for(i=0;attr[i]!=0x3038&&i<64;i+=2) L(" attr",attr[i],attr[i+1],0); if(cfgs&&sz>0) cfgs[0]=(void*)1; if(num)*num=1; return 1; }
void *eglCreateContext(void*d,void*c,void*sh,const s32*attr){ u32 id=++egl_ctr; L("eglCreateContext",id,(u32)sh,attr?attr[1]:0); return (void*)id; }
void *eglCreateWindowSurface(void*d,void*c,void*win,const s32*attr){ L("eglCreateWindowSurface",(u32)win,0,0); return win; }
u32 eglMakeCurrent(void*d,void*dr,void*rd,void*ctx){ L("eglMakeCurrent",(u32)dr,(u32)ctx,0); return 1; }
u32 eglSwapInterval(void*d,s32 i){ return 1; }
u32 eglGetError(void){ return 0x3000; }
static u32 nswap;
u32 eglSwapBuffers(void*d,void*surf){
  { static int bt; if(bt++<2){ volatile u32 m; u32 *sp=(u32*)&m; char b[220]; int n=0,c=0; b[0]=0; extern int snprintf(char*,unsigned long,const char*,...); n=snprintf(b,220,"swapbt lr=%x:",(u32)__builtin_return_address(0)); for(int i=0;i<600&&c<16&&n<200;i++){ u32 w=sp[i]; if(w>0x100000&&w<0x3000000&&!(w&3)){ u32 ins=*(u32*)(w-4); if((ins&0x0f000000)==0x0b000000||(ins&0x0ffffff0)==0x012fff30){ n+=snprintf(b+n,220-n," %x",w); c++; } } } br_log(b); } }
  u32*p,*rep; obj_t*o=(obj_t*)surf; u32 w=o?o->w:1920,h=o?o->h:720; LOCK(); p=br_begin(OP_SWAP,2); p[0]=w;p[1]=h; br_sync(&rep); UNLOCK();
  if(++nswap<5) L("eglSwapBuffers",nswap,w,h); return 1; }
static int streq(const char*a,const char*b){ return strcmp(a,b)==0; }
/* superficie do mapa (CHmiSurfaceRedirection): a imagem e a textura vivem no host; o EGLImage so identifica a superficie atual */
u32 map_cur[3];
static void *egl_create_image(void*d,void*c,u32 tgt,void*buf,const s32*attr){ return buf?buf:(void*)1; }
static void gl_egl_image_target(u32 tgt,void*img){ u32*p; LOCK(); p=br_begin(OP_MAPBIND,3); p[0]=map_cur[0]; p[1]=map_cur[1]; p[2]=map_cur[2]; UNLOCK(); br_logx("map: textura ligada a superficie",map_cur[0],map_cur[1],map_cur[2]); }
void *eglGetProcAddress(const char*name){ u32 i; L("eglGetProcAddress",0,0,0); br_log(name);
  if(streq(name,"eglCreateImageKHR")) return (void*)egl_create_image; if(streq(name,"glEGLImageTargetTexture2DOES")) return (void*)gl_egl_image_target;
  for(i=0;gl_funcs[i].n;i++) if(streq(gl_funcs[i].n,name)) return gl_funcs[i].p; return 0; }
