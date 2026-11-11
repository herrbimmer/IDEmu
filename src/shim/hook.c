/* hook.c: runtime patches into the HMI's libraries (coding profile, etc.) */
#include "common.h"
#include "hook_profile.h"
void *hook_home(void); static unsigned char *disp_svc;
#define AUTO_POWER_TICKS 200
extern void *dlopen(const char*,int); extern void *dlsym(void*,const char*);
extern int mprotect(void*,unsigned long,int);
void *hk_sym(const char*lib,const char*s){ void*h=dlopen(lib,2); return h?dlsym(h,s):0; }
extern void *mmap(void*,unsigned long,int,int,int,long); extern int *__get_errno_ptr(void);
extern int munmap(void*,unsigned long);
/* shared-library text can't be made writable: replace the page(s) by private anonymous copies.
   Each page only once: mapping again would put a zero page under code that other threads may be running (and lose earlier patches).
   The copy goes through a temporary page of its own, not a static buffer shared between threads. */
#define MAXPRIV 128
static u32 priv_pg[MAXPRIV]; static u32 npriv;
static int unshare(u32 pg){ for(u32 i=0;i<npriv;i++) if(priv_pg[i]==pg) return 0;
  if(npriv>=MAXPRIV){ br_logx("hook: too many patched pages",pg,0,0); return -1; }
  u8 *tmp=(u8*)mmap(0,0x1000,0x300,0x80002,-1,0); if((int)tmp==-1){ br_logx("hook: tmp mmap FAILED",pg,*__get_errno_ptr(),0); return -1; }
  memcpy(tmp,(void*)pg,0x1000);
  void*r=mmap((void*)pg,0x1000,0x700,0x80012,-1,0); if((int)r==-1){ br_logx("hook: mmap FAILED",pg,*__get_errno_ptr(),0); munmap(tmp,0x1000); return -1; }
  memcpy((void*)pg,tmp,0x1000); munmap(tmp,0x1000); priv_pg[npriv++]=pg; return 0; }
int hk_patch(void*target,void*fn){ if(!target||!fn){ br_logx("hook: invalid patch target",(u32)target,(u32)fn,0); return -1; }
  u32 a=(u32)target&~1u; u32 pg=a&~0xfffu; if(unshare(pg)) return -1; if(((a+7)&~0xfffu)!=pg&&unshare(pg+0x1000)) return -1;
  u32 *p=(u32*)a; p[0]=0xe51ff004; p[1]=(u32)fn; return 0; }
int hk(const char*lib,const char*s,void*fn){ void*t=hk_sym(lib,s); if(!t){ br_logx(s,0xdead,0,0); return -1; } int r=hk_patch(t,fn); br_logx(s,0x600d,(u32)t,r); return r; }
/* trampoline: first two instructions + jump back. "ldr rX,[pc,#imm]" (literal pool) is rewritten to load the same value from the
   trampoline (t[4], t[5]); other pc-relative instructions can't be moved and are only logged. */
static u32 tramp_ins(u32 a,int i,u32 *t){ u32 ins=((u32*)a)[i];
  if((ins&0xff7f0000)==0xe51f0000&&((ins>>12)&15)!=15){ u32 imm=ins&0xfff,at=a+4*i+8; t[4+i]=*(u32*)((ins&(1u<<23))?at+imm:at-imm); br_logx("hook: literal relocated",a,i,t[4+i]); return 0xe59f0008|(ins&0xf000); }   /* t+4i+8+8 = &t[4+i] */
  if(!(ins&0x0c000000)&&(((ins>>16)&15)==15||(!(ins&0x02000000)&&(ins&15)==15))) br_logx("hook: pc-relative prologue, trampoline may be wrong",a,i,ins);
  return ins; }
void *hk_tramp(u32 a,void *fn){ if(!a||!fn){ br_logx("hook: invalid trampoline target",a,(u32)fn,0); return 0; }
  u32 *t=(u32*)mmap(0,4096,0x700,0x80002,-1,0); if((int)t==-1){ br_logx("hook: tramp mmap failed",a,0,0); return 0; }
  t[0]=tramp_ins(a,0,t); t[1]=tramp_ins(a,1,t); t[2]=0xe51ff004; t[3]=a+8;
  if(hk_patch((void*)a,fn)){ munmap(t,4096); return 0; } return t; }

typedef struct { u32 addr,w0,w1,w2,w3; const char *name; } profile_sig;
static int sig_ok(const profile_sig *s){
  if(!s->addr){ br_logx(s->name,0xdead1e,0,0); return 0; }
#if PROFILE_CHECK
  u32 *p=(u32*)s->addr;
  if(p[0]!=s->w0||p[1]!=s->w1||p[2]!=s->w2||p[3]!=s->w3){
    br_logx(s->name,0xdead1e,p[0],p[1]); br_logx("expected",s->w0,s->w1,s->w2); return 0;
  }
#endif
  return 1;
}
static void *sig_tramp(const profile_sig *s,void *fn){ return sig_ok(s)?hk_tramp(s->addr,fn):0; }
static int sig_patch(const profile_sig *s,void *fn){ return sig_ok(s)?hk_patch((void*)s->addr,fn):-1; }
static void *sig_addr(const profile_sig *s){ return sig_ok(s)?(void*)s->addr:0; }

typedef struct { u16 blk,byte; u8 mask,val; } cod_t;
static const cod_t cod_builtin[]={
#include "coding_tab.inc"
};
/* IDEmu: the coding profile of the virtual car lives in /fs/shim/coding.tab (6-byte rows), written by the host builder */
extern int open(const char*,int,...); extern long read(int,void*,unsigned long); extern int close(int);
static const cod_t *cod=cod_builtin; static u32 NCOD=sizeof cod_builtin/sizeof cod_builtin[0]; static int cod_loaded;
static void cod_load(void){ if(cod_loaded) return; cod_loaded=1; int fd=open("/fs/shim/coding.tab",0); if(fd<0) return; static u8 buf[6*4096] __attribute__((aligned(4))); long n=0,r; while(n<(long)sizeof buf&&(r=read(fd,buf+n,sizeof buf-n))>0) n+=r; close(fd); if(n>=6){ cod=(const cod_t*)buf; NCOD=(u32)n/6; br_logx("coding: profile from /fs/shim/coding.tab, rows",NCOD,0,0); } }
static int (*getdef)(u32,const u8**,u32*);
static int hk_readCodingBlock(u8 *self,u8 *buf,u32 sz){ cod_load(); static const u8 map[17]={7,5,1,13,12,3,9,8,6,4,10,15,16,17,14,2,11};
  u16 blk=*(u16*)(self+4); u32 i; const u8*d=0; u32 n=0;
  if(blk<0x3000||blk>0x3010){ br_logx("coding: unknown block",blk,sz,0); return 1; }
  if(getdef) getdef(map[blk-0x3000],&d,&n);
  memset(buf,0,sz); if(d&&n) memcpy(buf,d,n<sz?n:sz);
  for(i=0;i<NCOD;i++) if(cod[i].blk==blk&&cod[i].byte<sz) buf[cod[i].byte]=(buf[cod[i].byte]&~cod[i].mask)|cod[i].val;
  br_logx("coding: block",blk,sz,n); return 1; }
static int hk_true(void){ return 1; }
/* the coding service only hands out streams once "coding available" is signalled by the (absent) syset server */
static void *(*dsi_ctor)(void*,u16);
static void *hk_openBinaryStream(u8 *svc,void *feature){ if(!dsi_ctor) return 0; u32 **o=(u32**)malloc(8); if(!o) return 0; dsi_ctor(o,*(u16*)(svc+0x10)); typedef int(*fn)(void*,void*); fn f=(fn)o[0][2]; if(f(o,feature)==0){ br_logx("coding: stream open failed",*(u16*)((u8*)feature+8),0,0); return 0; } return o; }
/* ---- controller input: host -> guest thread -> CHmiControllerEvent ---- */
static u8 *procs[256];
static u32 hk_getID(u8 *t){ u32 id=t[0xce]; if(!procs[id]){ procs[id]=t; br_logx("procunit",id,(u32)t,*(u32*)t); } return id; }
extern int pthread_create(void*,const void*,void*(*)(void*),void*);
/* CHmiProcUnit::CHmiProcUnit (C2): patched once, through a trampoline. Before, every construction restored the original code, called it and patched
   again: other threads could run half-patched code meanwhile, and each patch mapped a new zero page over live library text. */
static void *(*pu_c2_tramp)(void*,void*,u32);
static void *hk_pu_c2(u8 *t,void *disp,u32 id){ if(!pu_c2_tramp) return 0; void *r=pu_c2_tramp(t,disp,id); id&=255; procs[id]=t; br_logx("procunit",id,(u32)t,*(u32*)t); return r; }
static int app_unit=-1;
static void send_ctrl(u32 key,int pressed,int repeat,int longp,int unit){ void*(*mk)(void)=(void*(*)(void))0x736fa0; u8*p=procs[unit]; if(!p){ br_logx("input: no proc unit",unit,0,0); return; }
  u8 *ev=(u8*)mk(); *(u32*)(ev+0x18)=key; ev[0x1c]=pressed; *(int*)(ev+0x20)=repeat; ev[0x24]=longp;
  typedef void(*pushf)(void*,void*); ((pushf)((u32*)*(u32*)p)[7])(p,ev); }
extern void *_Z14getHmiProcUnitv(void);
static u8 *main_pu;
static u8 *(*get_proc)(void);
static void (*power_set)(void*,u32);
static void *(*ctrl_event_new)(void);
static void (*proc_push)(void*,void*);
static void (*ccs_button)(u32,u32,u32,u32);
static void (*map_notify)(void*,u32);
/* O HMI tem vários proc units (um por subsistema, cada um com seu thread e seu updateAliveTime); só o da aplicação trata o controlador. O main_pu é o do
   último thread a passar por hk_alive: empurrados nele, os eventos do controlador iam para a fila de um proc unit qualquer e se perdiam (no teste, 2 de 13
   giros chegavam). app_pu é o proc unit do thread que registra a tela inicial (hk_stc), o mesmo que despacha os eventos do controlador: push_ctrl usa ele. */
static u8 *app_pu;
/* Ligar o HMI ("auto power on"): no thread principal (updateAliveTime). */
static void auto_power_on(void){ static int t,done,failed; if(done||!hook_home()||++t<=AUTO_POWER_TICKS) return; done=1;
  if(!get_proc||!power_set){ if(!failed++){ br_log("power: unresolved get_proc/power_set"); } return; }
  u8*pu=get_proc(); if(!pu){ if(!failed++){ br_log("power: no main proc unit"); } return; }
  br_log("auto power on"); power_set(pu,3); ((u8*)hook_home())[HOME_POWER_FLAG]=1; ((u8*)hook_home())[HOME_AUX_FLAG]=0; }
/* Entrada do host: thread própria a cada 15 ms. Antes era lida em updateAliveTime, que com o relógio correto do guest (cntfrq) só roda ~1x/s com a tela parada: cada comando atrasava até 1 s.
   O giro do rotor vai direto para a fila do proc unit (vt[7]). Botões e comandos de depuração usam funções que exigem o thread principal (getHmiProcUnit por TLS, com assert): ficam num anel que
   hk_alive esvazia, e um evento vazio na fila acorda o laço principal para isso acontecer logo. */
void (*ilm_main_cb)(void); volatile int ilm_main_want;   /* avisos da ILM a entregar no thread principal (src/shim/ilm.c) */
typedef void(*pushf)(void*,void*);
static void push_ctrl(u32 key,u32 pressed,int param){ u8 *pu=app_pu?app_pu:main_pu;
  if(!pu||!ctrl_event_new||!proc_push){ static int n; if(n++<5) br_logx("input: unresolved",(u32)pu,(u32)ctrl_event_new,(u32)proc_push); return; }
  u8 *c=ctrl_event_new(); *(u32*)(c+0x18)=key; c[0x1c]=pressed; *(int*)(c+0x20)=param; c[0x24]=0; proc_push(pu,c); }
static void touch_send(u32 state,u32 x,u32 y,u32 hms);
#define RINGN 256
static u32 ring[RINGN][4]; static volatile u32 ring_w, ring_r; static volatile int wake_pending;
void input_pump(void){ u32 *p,*rep; u32 n;
  if(!main_pu) return;
  LOCK(); p=br_begin(OP_GETINPUT,0); n=br_sync(&rep); static u32 ev[64*4]; if(n>sizeof ev) n=sizeof ev; memcpy(ev,rep,n); UNLOCK();
  int wake=0;
  for(u32 i=0;i<n/16;i++){ u32 *e=ev+i*4;
    if(e[0]==40){ touch_send(e[1],e[2]&0xffff,e[2]>>16,e[3]==0xffff?0:e[3]); continue; }   /* toque: direto da thread de entrada (a entrega é assíncrona) e sem o evento de controlador que "acordaria" o laço: ele faria o HMI achar que o iDrive tomou a entrada */
    if(e[0]==2){ push_ctrl(e[1],0,(int)e[2]); continue; }   /* rotary: key=13 right / 14 left, val=detents */
#if HMI_FEATURE_MAP
    if(e[0]==30){ void *rd=*(void**)A_MAP_REDIRECTION; if(rd&&map_notify) map_notify(rd,e[1]); continue; }   /* imagem nova do mapa: o que o sinal do LayerManager faria (CHmiSurfaceRedirection::notifyUpdate) */
#endif
    if(ring_w-ring_r<RINGN){ memcpy(ring[ring_w%RINGN],e,16); __atomic_add_fetch(&ring_w,1,__ATOMIC_RELEASE); wake=1; }
  }
  if((wake||ilm_main_want)&&!wake_pending){ wake_pending=1; push_ctrl(0,0,0); }   /* um só evento de acordar até o thread da aplicação passar por input_main: com ele ocupado (abrindo um menu) saíam dezenas, um a cada 15 ms */
}
/* toque na tela (CID): monta um CTouchData e o entrega a CTouchDataClient::forwardTouchData (assíncrono), como o driver do touchscreen faria.
   Layout (ver docs/TOQUE.md): CTouchData{vptr, vector<dedo> @4, u8 @0x10 (tem de ser 0), tempo @0x14, origem @0x18}; dedo = 10 bytes {u16 x,u16 y,u16 z,u8 tipo,u8 estado,u8 id,u8 0};
   estado 1 = toca, 2 = move/segura, 3 = solta. O shared_ptr é montado à mão com contagem alta: o objeto nunca é liberado. */
extern int clock_gettime(int,void*);
static void *tdc_client; static void *(*tdc_c1)(void*,u32,u32); static void *(*tdc_c2)(void*,u32,u32);
/* o construtor começa com ldr/add relativos ao PC (base da GOT): o trampolim refaz essas duas e salta para depois do prólogo (0x18) */
static void *hk_tdc_tramp(u32 a,void *fn){ if(!a||!fn) return 0; u32 *t=(u32*)mmap(0,4096,0x700,0x80002,-1,0); if((int)t==-1) return 0;
  t[0]=((u32*)a)[0]; t[1]=((u32*)a)[2]; t[2]=0xe59f5008; t[3]=0xe59f3008; t[4]=((u32*)a)[4]; t[5]=0xe59ff004; t[6]=0x39e7930; t[7]=0x7f60; t[8]=a+0x18; hk_patch((void*)a,fn); return t; }
static void *hk_tdc_a(void *t,u32 a,u32 b){ void *r=tdc_c1(t,a,b); if(!tdc_client){ tdc_client=t; br_logx("touch client C1",(u32)t,0,0); } return r; }
static void *hk_tdc_b(void *t,u32 a,u32 b){ void *r=tdc_c2(t,a,b); if(!tdc_client){ tdc_client=t; br_logx("touch client C2",(u32)t,0,0); } return r; }
/* o serviço guarda, por origem, se ela está habilitada (std::map<int,bool> em +0x28); num F-series sem touchscreen a origem 1 fica desligada */
static void touch_enable(void){ u32 *l=*(u32**)((u8*)tdc_client+0x1fc); if(!l||!l[2]) return; int key=1; u8 *p=((u8*(*)(void*,int*))0x2a01514)((u8*)l[2]+0x28,&key);
  if(!*p){ *p=1; br_logx("touch: origem 1 habilitada",(u32)p,0,0); } }
static void touch_send(u32 state,u32 x,u32 y,u32 hms){
  if(!tdc_client){ static int n; if(n++<5) br_logx("touch: sem cliente",state,x,y); return; }
  touch_enable();
  /* sem o monitor de verdade, o serviço de display acha que a tela está apagada e usa o primeiro toque só para acordá-la: marca como ligada */
  if(disp_svc&&(!disp_svc[0x3c]||!disp_svc[0x3d])){ disp_svc[0x3c]=1; disp_svc[0x3d]=1; ((void(*)(void*,int))0x2df744)(disp_svc,1); br_logx("touch: display marcado como ligado",(u32)disp_svc,0,0); }
  /* o tratador de gestos descarta o primeiro toque quando acha que a tela está apagada (+0x30 == 0): ele só a "acorda" */
  { u32 *ip=*(u32**)((u8*)tdc_client+0xd8); int k=0; while(ip&&k<10){ if(ip[3]==0x3384e8){ u8 *ob=(u8*)ip[2]+((int)ip[4]>>1); if(!ob[0x30]){ ob[0x30]=1; br_logx("touch: gestos ativos",(u32)ob,0,0); } } ip=(u32*)ip[0]; k++; } }
  u8 *f=(u8*)malloc(16); memset(f,0,16); *(u16*)f=(u16)x; *(u16*)(f+2)=(u16)y; *(u16*)(f+4)=30; f[6]=0; f[7]=(u8)state; f[8]=1;
  u32 vec[3]={(u32)f,(u32)(f+10),(u32)(f+10)};
  u8 *o=(u8*)malloc(0x20); memset(o,0,0x20);
  u32 ts[2]={0,0}; clock_gettime(2,ts); u32 ms=hms?hms:ts[0]*1000+ts[1]/1000000;   /* hms: hora em que o Mac enviou o toque (o laço do HMI ocioso só roda ~1 vez por segundo e juntaria descida e subida) */
  ((void*(*)(void*,void*,u32,u32,u32))0x2a26914)(o,vec,0,ms,1);
  u32 *cb=(u32*)malloc(16); cb[0]=0x39e2900; cb[1]=0x10000000; cb[2]=1; cb[3]=(u32)o;
  u32 sp[2]={(u32)o,(u32)cb};
  ((void(*)(void*,void*))0x2a22600)(tdc_client,sp);   /* forwardTouchData (assíncrono): enfileira forwardTouchDataSync no processo certo, como o driver faria */
}
/* no thread principal */
static void input_main(u8 *pu){
  /* o tratamento de uma tecla pode rodar um laço aninhado e voltar a updateAliveTime: sem esta trava, o mesmo evento era tratado sem fim (HMI travado, morto pelo watchdog) */
  static int busy; if(busy) return; busy=1; wake_pending=0;
  while(ring_r!=__atomic_load_n(&ring_w,__ATOMIC_ACQUIRE)){ u32 ee[4]; memcpy(ee,ring[ring_r%RINGN],16); __atomic_add_fetch(&ring_r,1,__ATOMIC_RELEASE); u32 *e=ee;
    if(e[0]==1&&e[3]==1){ push_ctrl(e[1],e[2]!=0,1); }
    else if(e[0]==40){ touch_send(e[1],e[2]&0xffff,e[2]>>16,e[3]==0xffff?0:e[3]); }
#if HMI_FEATURE_DEBUG
    else if(e[0]==9){ void*h=hook_home(); br_logx("home app",(u32)h,h?*((u8*)h+0x338):0,0); if(h) ((void(*)(void*,int))0x2f7114)(h,e[1]); }
    else if(e[0]==7){ u8 *o=((u8*(*)(void))0x228384)(); u8 *x=o?*(u8**)(o+8):0; u8 *h=x?((u8*(*)(void*))0x60af10)(x):0; br_logx("dbg obj",(u32)o,(u32)x,(u32)h); if(h){ u32 vt=*(u32*)h; br_logx("dbg handler vt",vt,*(u32*)(vt+0xc),*(u32*)(vt+8)); } }
    else if(e[0]==6){ br_logx("force display",(u32)disp_svc,disp_svc?disp_svc[0x3c]:0,disp_svc?disp_svc[0x3d]:0); if(disp_svc){ disp_svc[0x3c]=1; disp_svc[0x3d]=1; ((void(*)(void*,int))0x2df744)(disp_svc,1); } }
    else if(e[0]==5){ u8*h=(u8*)hook_home(); if(h){ br_logx("home flags",h[0x338]|h[0x339]<<8|h[0x33a]<<16|h[0x33b]<<24,h[0x33c],e[1]); h[0x33b]=e[1]; h[0x33a]=e[2]; } }
    else if(e[0]==8){ void*h=hook_home(); int N=-1; for(int o=-0x2000;o<0x2000&&h;o+=4){ if(*(void**)(pu+o+MAIN_HOME_OFFSET)==h){ N=o; break; } } br_logx("powermode this-offset",N,(u32)h,e[1]); if(N!=-1&&power_set) power_set(pu+N,e[1]); }
#endif
    else if(e[0]==1){ /* button: key event + controller event, as CHmiCCSController::onCCSPushButton does */
      if(ccs_button) ccs_button(e[1],e[2]!=0,0,0); push_ctrl(e[1],e[2]!=0,1); }
  }
  if(ilm_main_want&&ilm_main_cb){ ilm_main_want=0; ilm_main_cb(); }
  busy=0; }
static void *home_app; void *hook_home(void){ return home_app; } static int (*stc_tramp)(void*,u32,u32,u32);
static int hk_stc(void *t,u32 a,u32 b,u32 c){ home_app=t; if(!app_pu&&get_proc){ app_pu=get_proc(); br_logx("app proc unit",(u32)app_pu,app_pu?*(u32*)app_pu:0,0); } return stc_tramp?stc_tramp(t,a,b,c):0; }
static u32 (*reg_tramp)(void*,void*,u32,u32,u32,u32);
static u32 hk_reg(void *pu,void *tgt,u32 fn,u32 adj,u32 grp,u32 ty){ if(grp==*(u16*)0x3af08cc||(u16)grp==*(u16*)0x3af08cc) br_logx("reg ctrl listener",fn,(u32)tgt,ty); return reg_tramp(pu,tgt,fn,adj,grp,ty); }
static u32 (*add_tramp)(void*,void*,u32,u32,u32,u32);
static u32 hk_add(void *d,void *tgt,u32 fn,u32 adj,u32 grp,u32 ty){ if((u16)grp==*(u16*)0x3af08cc) { u32 vt=*(u32*)tgt; br_logx("add ctrl listener",fn,(u32)tgt,vt); if(fn<0x1000){ br_logx(" virt target",*(u32*)(vt+fn),adj,0); } } return add_tramp(d,tgt,fn,adj,grp,ty); }
extern int snprintf(char*,unsigned long,const char*,...);
void hk_bt(const char*tag){ volatile u32 m; u32 *sp=(u32*)&m; char b[260]; int n=0,c=0; n=snprintf(b,260,"BT %s:",tag); for(int i=0;i<500&&c<14&&n<230;i++){ u32 w=sp[i]; if(w>0x100000&&w<0x3000000&&!(w&3)){ u32 ins=*(u32*)(w-4); if((ins&0x0f000000)==0x0b000000||(ins&0x0ffffff0)==0x012fff30){ n+=snprintf(b+n,260-n," %x",w); c++; } } } br_log(b); }
static u32 (*wh_tramp)(void*,u32,u32,u32);
static u32 hk_wh(void *t,u32 a,u32 b,u32 c){ static int n; if(n++<8){ br_logx("widget handle",(u32)t,a,b); hk_bt("wh"); } return wh_tramp(t,a,b,c); }
static u32 (*lh_tramp)(void*,u32,u32,u32,u32); static u32 (*ch_tramp)(void*,u32,u32,u32,u32);
static u32 hk_lh(void *t,u32 a,u32 b,u32 c,u32 d){ u32 r=lh_tramp(t,a,b,c,d); br_logx("list handler",a,b,r); return r; }
static u32 hk_ch(void *t,u32 a,u32 b,u32 c,u32 d){ u32 r=ch_tramp(t,a,b,c,d); br_logx("container handler",a,b,r); return r; }
static u32 hk_pmd(void){ return 0x64; } /* PMD_Fullon_useron */
static u32 hk_pm(void){ return 3; }     /* PM_fullon_useron */
static u32 (*eds_tramp)(void*,u32,u32,u32);
static u32 hk_eds(void *t,u32 a,u32 b,u32 c){ if(!disp_svc) br_logx("display service",(u32)t,0,0); disp_svc=(u8*)t; return eds_tramp(t,a,b,c); }
static u32 (*eds2_tramp)(void*,u32,u32,u32);
static u32 hk_eds2(void *t,u32 a,u32 b,u32 c){ if(!disp_svc) br_logx("display service (2)",(u32)t,0,0); disp_svc=(u8*)t; return eds2_tramp(t,a,b,c); }
static void (*alive_tramp)(void*);
extern int usleep(unsigned);
static void *input_thread(void *a){ for(;;){ usleep(15000); input_pump(); } return 0; }
static void hk_alive(void *t){ static int n; u8 *main=get_proc?get_proc():0; if(main&&t==main){ if(n++<3) br_logx("alive on main unit",(u32)t,0,0); main_pu=(u8*)t; auto_power_on(); input_main((u8*)t); { static int started; static u32 tid[8]; if(!started){ started=1; pthread_create(tid,0,input_thread,0); } } } if(alive_tramp) alive_tramp(t); }
static void (*lua_err_tramp)(u8*);
static void hk_luaerr(u8 *L){ u8 *top=*(u8**)(L+8); u32 v=*(u32*)(top-16); u32 tt=*(u32*)(top-8); static int n; if(n<400&&tt==4&&v){ n++; char b[250]; const char*m=(const char*)(v+16); u32 i=0; b[0]='L';b[1]='U';b[2]='A';b[3]=':';b[4]=' '; while(m[i]&&i<230){ b[5+i]=m[i]; i++; } b[5+i]=0; br_log(b); } lua_err_tramp(L); }
/* IDEmu diag: log every distinct (variant id -> result) the HMI asks; optional overrides from /fs/shim/variants.bin (u32 LE: id | forced<<31) */
static u32 (*isv_tramp)(void*,u32);
static u8 isv_seen[8192]; static u32 isv_force[512]; static u32 nforce, force_loaded;
static void isv_load(void){ if(force_loaded) return; force_loaded=1; int fd=open("/fs/shim/variants.bin",0); if(fd<0) return; long n=0,r; static u8 b[2048] __attribute__((aligned(4))); while(n<(long)sizeof b&&(r=read(fd,b+n,sizeof b-n))>0) n+=r; close(fd); nforce=(u32)n/4; for(u32 i=0;i<nforce;i++) isv_force[i]=((u32*)b)[i]; br_logx("variants: overrides",nforce,0,0); }
static u32 hk_isv(void *t,u32 id){ isv_load(); if(!isv_tramp) return 0; u32 r=isv_tramp(t,id)&0xff; u32 i; for(i=0;i<nforce;i++) if((isv_force[i]&0xffff)==id){ r=isv_force[i]>>31; break; }
  if(id<65536&&!(isv_seen[id>>3]&(1<<(id&7)))){ isv_seen[id>>3]|=(1<<(id&7)); br_logx("variant",id,r,i<nforce); } return r; }
/* diag: CDevCarTpmStatusImpl::updateStatus (0xd98b44): estado interno depois de cada chamada */
/* O RDC real reenvia telegramas continuamente; no emulador o valor de CTyresStatus e fixo. O temporizador de 17,5 s (relogio do guest ~6x mais rapido que o do host) do
   CDevCarTpmStatusImpl (callback 0xd99218) declararia "sem dados" (estado 0x60 -> traços no lugar das pressões): neutralizado. */
static void hk_tpm_timer(void){ }
static void (*tpm_tramp)(u8*);
static void hk_tpm(u8 *t){ tpm_tramp(t); static u32 last[4]; static u32 n; u32 a=(u32)t[0x60]|((u32)t[0x68]<<8)|((u32)t[0x69]<<16)|((u32)t[0x6a]<<24); u32 b=(u32)t[0x0c]|((u32)t[0x58]<<8)|((u32)t[0x70]<<16)|((u32)t[0x6d]<<24); u32 c=(u32)t[0x6e]|((u32)t[0x6f]<<8);
  if(n<200&&(a!=last[0]||b!=last[1]||c!=last[2])){ last[0]=a;last[1]=b;last[2]=c; n++; br_logx("tpm: st60|68|69|6a",a,b,c); } }
/* Mapa: sem o processo de navegacao nao ha LayerManager para criar /dev/layermanager_<n>_{img,cmd}. CHmiSurfaceRedirection::mapSurfaceBuffer (0x2a0d728)
   so precisa preencher SharedSurface (+8 tamanho, +0xc imagem, +0x10 RemoteImageData); os pixels ficam na textura do host (OP_MAPBIND, src/glhost/map.c). */
extern u32 map_cur[3]; extern int pthread_mutex_init(void*,const void*); extern int getpid(void); extern int munmap(void*,unsigned long);
static int hk_mapsurf(void *self,u32 surf,u32 w,u32 h,u8 *out){ if(!w||!h) return 0; u32 len=w*h*4; void *img=mmap(0,len,0x300,0x80002,-1,0); if((int)img==-1){ br_logx("map: sem memoria",surf,w,h); return 0; }
  u32 *m=(u32*)calloc(1,0x38); m[0]=8; m[1]=w; m[2]=h; m[3]=w*4; m[4]=getpid(); pthread_mutex_init(m+5,0); *(u32*)(out+8)=len; *(void**)(out+0xc)=img; *(void**)(out+0x10)=m;
  map_cur[0]=surf; map_cur[1]=w; map_cur[2]=h; br_logx("map: superficie criada",surf,w,h); return 1; }
static void hk_unmapsurf(void *self,u32 surf,u8 *sh){ void *img=*(void**)(sh+0xc); u32 len=*(u32*)(sh+8); void *m=*(void**)(sh+0x10); if(img) munmap(img,len); if(m) free(m); *(u32*)(sh+8)=0; *(u32*)(sh+0xc)=0; *(u32*)(sh+0x10)=0; br_logx("map: superficie removida",surf,0,0); }
/* diagnóstico: sem o gerenciador de falhas do carro, uma queda do HMI não deixava rastro; registra de onde veio e devolve ao tratamento padrão */
extern void (*signal(int,void(*)(int)))(int);
static void crash_h(int sg,u32 *info,u32 *uc){ static int n; if(n++==0){ br_logx("CRASH sinal",(u32)sg,(u32)info,(u32)uc);
    if((u32)info>0x1000&&(u32)info<0xf0000000){ br_logx("CRASH info",info[0],info[1],info[2]); br_logx("CRASH info2",info[3],info[4],info[5]); }
    if((u32)uc>0x1000&&(u32)uc<0xf0000000){ for(int i=0;i<64;i+=4) if(uc[i]||uc[i+1]||uc[i+2]||uc[i+3]){ br_logx("CRASH ctx",i,uc[i],uc[i+1]); br_logx(" ",uc[i+2],uc[i+3],0); } }
    hk_bt("crash"); } signal(sg,(void(*)(int))0); }
void install_hooks(void){ static int done; if(__atomic_exchange_n(&done,1,__ATOMIC_ACQ_REL)) return;
#ifdef CRASHHK   /* diagnóstico de quedas (-DCRASHHK): ligado, o iDrive 5 não termina de subir (sinal capturado no boot); desligado por padrão */
  signal(11,(void(*)(int))crash_h); signal(10,(void(*)(int))crash_h); signal(4,(void(*)(int))crash_h); signal(8,(void(*)(int))crash_h);
#endif
  static const profile_sig stc={A_STC,W0_STC,W1_STC,W2_STC,W3_STC,"stc"};
  static const profile_sig pmd={A_PMD,W0_PMD,W1_PMD,W2_PMD,W3_PMD,"pmd"};
  static const profile_sig pm={A_PM,W0_PM,W1_PM,W2_PM,W3_PM,"pm"};
  static const profile_sig pwr={A_POWER_SET,W0_POWER_SET,W1_POWER_SET,W2_POWER_SET,W3_POWER_SET,"power_set"};
  static const profile_sig cev={A_CTRL_EVENT,W0_CTRL_EVENT,W1_CTRL_EVENT,W2_CTRL_EVENT,W3_CTRL_EVENT,"ctrl_event"};
  static const profile_sig cbtn={A_CCS_BUTTON,W0_CCS_BUTTON,W1_CCS_BUTTON,W2_CCS_BUTTON,W3_CCS_BUTTON,"ccs_button"};
  static const profile_sig maps={A_MAPSURF,W0_MAPSURF,W1_MAPSURF,W2_MAPSURF,W3_MAPSURF,"mapsurf"};
  static const profile_sig unmap={A_UNMAP,W0_UNMAP,W1_UNMAP,W2_UNMAP,W3_UNMAP,"unmap"};
  static const profile_sig mn={A_MAP_NOTIFY,W0_MAP_NOTIFY,W1_MAP_NOTIFY,W2_MAP_NOTIFY,W3_MAP_NOTIFY,"map_notify"};

  get_proc=(u8*(*)(void))hk_sym("libhmicom.so","_Z14getHmiProcUnitv");
  proc_push=(void(*)(void*,void*))hk_sym("libhmicom.so","_ZN12CHmiProcUnit9pushEventEP9CHmiEvent");
  power_set=(void(*)(void*,u32))sig_addr(&pwr);
  ctrl_event_new=(void*(*)(void))sig_addr(&cev);
  ccs_button=(void(*)(u32,u32,u32,u32))sig_addr(&cbtn);

  getdef=(int(*)(u32,const u8**,u32*))hk_sym("libhmicoding.so","sysetDefaults_getBuffer");
  dsi_ctor=(void*(*)(void*,u16))hk_sym("libhmicoding.so","_ZN16CDsiBinaryStreamC1Et");
  hk("libhmicoding.so","_ZN16CDsiBinaryStream15readCodingBlockEPvj",hk_readCodingBlock);
  hk("libhmicoding.so","_ZN17CHmiCodingService16openBinaryStreamEPK14CODING_FEATURE",hk_openBinaryStream);
  hk("libhmicoding.so","_ZN17CHmiVariantServer15isVACodingValidEv",hk_true);
  { void *a=hk_sym("libhmicoding.so","_ZN17CHmiVariantServer12isVariantSetEj"); if(a) isv_tramp=(u32(*)(void*,u32))hk_tramp((u32)a,hk_isv); }

  stc_tramp=(int(*)(void*,u32,u32,u32))sig_tramp(&stc,hk_stc);
  sig_patch(&pmd,hk_pmd); sig_patch(&pm,hk_pm);
  { void *a=hk_sym("libhmicom.so","_ZN12CHmiProcUnit15updateAliveTimeEv"); if(a) alive_tramp=(void(*)(void*))hk_tramp((u32)a,hk_alive); }
  { void *a=hk_sym("libhmicom.so","_ZN12CHmiProcUnitC2ER18CHmiMainDispatcherh"); if(a) pu_c2_tramp=(void*(*)(void*,void*,u32))hk_tramp((u32)a,hk_pu_c2); }

#if HMI_FEATURE_TOUCH
  eds_tramp=(u32(*)(void*,u32,u32,u32))hk_tramp(0x2df744,hk_eds); eds2_tramp=(u32(*)(void*,u32,u32,u32))hk_tramp(0x2dfe98,hk_eds2);
  tdc_c1=(void*(*)(void*,u32,u32))hk_tdc_tramp(0x2a24660,hk_tdc_a); tdc_c2=(void*(*)(void*,u32,u32))hk_tdc_tramp(0x2a24e48,hk_tdc_b);
#endif
#if HMI_FEATURE_MAP
  map_notify=(void(*)(void*,u32))sig_addr(&mn);
  sig_patch(&maps,hk_mapsurf); sig_patch(&unmap,hk_unmapsurf);
#endif
#if HMI_FEATURE_LUA
  lua_err_tramp=(void(*)(u8*))hk_tramp(0x2a4e9b8,hk_luaerr);
#endif
#if HMI_FEATURE_TPM
  tpm_tramp=(void(*)(u8*))hk_tramp(0xd98b44,hk_tpm);
  hk_patch((void*)0xd99218,hk_tpm_timer);
#endif
}
