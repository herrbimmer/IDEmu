/* Fake libilmClient: no LayerManagerService; the HMI's EGL window goes straight to the host.
   Layer notifications are answered so that WAL3D believes its layers are visible and keeps rendering. */
#include "common.h"
typedef u32 U;
#define OK(n) int n(U a,U b,U c,U d){ br_logx("ilm: " #n,a,b,c); return 0; }
typedef void (*notif_t)(U layer,void *props,U mask);
typedef struct { U id; notif_t cb; int vis; int pending; float opacity; U dx,dy,dw,dh; U surf; } lay_t;
static lay_t lay[64]; static int nlay; static U next_layer=1000;
static lay_t *get(U id){ for(int i=0;i<nlay;i++) if(lay[i].id==id) return &lay[i]; if(nlay<64){ lay_t*l=&lay[nlay++]; l->id=id; l->vis=1; l->opacity=1.0f; return l; } return &lay[63]; }
static void fire(lay_t *l,U mask){ struct { float f[11]; U orient; U vis; U rest[16]; } p; if(!l->cb) return; memset(&p,0,sizeof p); p.f[0]=l->opacity; p.f[3]=1440;p.f[4]=540;p.f[5]=1440;p.f[6]=540;p.f[9]=1440;p.f[10]=540; ((U*)&p)[13]=l->vis; /* CWal3dNBTevo::visibilityChanged lê a visibilidade em +0x34 */ br_logx("ilm: notify",l->id,l->vis,mask); l->cb(l->id,&p,mask); }
/* A superficie do mapa fora de redirecionamento e composta por baixo da camada do HMI, no retangulo de destino da camada (host: src/glhost/map.c). */
static struct { U id,w,h; int vis,redir; } srf[32]; static int nsrf;
static int sidx(U id){ int k; for(k=0;k<nsrf;k++) if(srf[k].id==id) return k; if(nsrf==32) return 31; srf[nsrf].id=id; return nsrf++; }
static int is_map_surface(U id){ return id==0x201; }
static void map_sync(void){ static U last[5]; U v[5]={0,0,0,0,0}; for(int i=0;i<nlay;i++){ lay_t*l=&lay[i]; if(!l->surf||!is_map_surface(l->surf)) continue; int k=sidx(l->surf); if(l->vis&&srf[k].vis&&!srf[k].redir){ v[0]=1; v[1]=l->dx; v[2]=l->dy; v[3]=l->dw; v[4]=l->dh; } }
  if(memcmp(v,last,sizeof v)){ memcpy(last,v,sizeof v); u32*p; LOCK(); p=br_begin(OP_MAPLAYER,5); memcpy(p,v,sizeof v); UNLOCK(); br_logx("ilm: camada do mapa",v[0],v[3],v[4]); } }
/* CWal3dNBTevo bloqueia a camada logo depois de pedir para mostrá-la e espera o aviso de visibilidade para desbloquear: avisar dentro do commit chegava antes do bloqueio e a camada
   ficava bloqueada (mapa preto ao voltar do menu OPTION). O aviso vai na volta seguinte do laço principal (src/shim/hook.c): em outro thread derruba o HMI, que usa estado por thread nesse caminho. */
extern void (*ilm_main_cb)(void); extern volatile int ilm_main_want;
static void ilm_deliver(void){ for(int i=0;i<nlay;i++) if(lay[i].pending==2){ lay[i].pending=0; fire(&lay[i],2); } }   /* 2 = ILM_NOTIFICATION_VISIBILITY */
/* Projected video (CarPlay: the HMI puts Connectivity's screen window, surface 0x500, in its layer 0x800d0000): in IDEmu nothing
   renders that window, so the host draws a placeholder in the layer's destination rectangle, under the HMI (src/glhost/map.c). */
static int is_video_surface(U id){ return id==0x500; }
static void video_sync(void){ static U last[5]; U v[5]={0,0,0,0,0}; for(int i=0;i<nlay;i++){ lay_t*l=&lay[i]; if(!l->surf||!is_video_surface(l->surf)) continue; if(l->vis&&l->dw&&l->dh){ v[0]=1; v[1]=l->dx; v[2]=l->dy; v[3]=l->dw; v[4]=l->dh; } }
  if(memcmp(v,last,sizeof v)){ memcpy(last,v,sizeof v); u32*p; LOCK(); p=br_begin(OP_VIDLAYER,5); memcpy(p,v,sizeof v); UNLOCK(); br_logx("ilm: camada de video",v[0],(v[1]&0xffff)|(v[2]<<16),(v[3]&0xffff)|(v[4]<<16)); } }
int ilm_commitChanges(void){ int any=0; for(int i=0;i<nlay;i++) if(lay[i].pending){ lay[i].pending=2; any=1; } map_sync(); video_sync(); if(any){ ilm_main_cb=ilm_deliver; ilm_main_want=1; } return 0; }
int ilm_layerSetVisibility(U id,u8 v){ lay_t*l=get(id); br_logx("ilm: layerSetVisibility",id,v,0); l->vis=v; l->pending=1; return 0; }
int ilm_layerGetVisibility(U id,u8 *v){ if(v)*v=get(id)->vis; return 0; }
int ilm_layerSetOpacity(U id,float o){ get(id)->opacity=o; return 0; }
int ilm_layerAddNotification(U id,notif_t cb){ lay_t*l=get(id); l->cb=cb; br_logx("ilm: addNotification",id,(U)cb,l->vis); l->pending=1; return 0; }
OK(ilm_init) OK(ilm_destroy) OK(ilm_displaySetRenderOrder)
int ilm_layerAddSurface(U id,U s){ br_logx("ilm: ilm_layerAddSurface",id,s,0); if(is_map_surface(s)||!get(id)->surf) get(id)->surf=s; return 0; }
int ilm_layerSetDestinationRectangle(U id,U x,U y,U w,U h){ lay_t*l=get(id); if(l->dx!=x||l->dy!=y||l->dw!=w||l->dh!=h) br_logx("ilm: layerDest id/x|y<<16/w|h<<16",id,(x&0xffff)|(y<<16),(w&0xffff)|(h<<16)); l->dx=x; l->dy=y; l->dw=w; l->dh=h; return 0; }
OK(ilm_layerSetRenderOrder) int ilm_layerSetSourceRectangle(U id,U x,U y,U w,U h){ br_logx("ilm: layerSrc id/x|y<<16/w|h<<16",id,(x&0xffff)|(y<<16),(w&0xffff)|(h<<16)); return 0; }
OK(ilm_surfaceSetSourceRectangle)
int ilm_startSurfaceRedirect(U id,void *ev){ srf[sidx(id)].redir=1; return 0; }
int ilm_stopSurfaceRedirect(U id){ srf[sidx(id)].redir=0; if(is_map_surface(id)) map_sync(); /* com a superfície travada, o HMI só para o redirecionamento depois do último commit */ return 0; }
int ilm_surfaceSetVisibility(U id,u8 v){ srf[sidx(id)].vis=v; if(is_map_surface(id)) map_sync(); /* às vezes não vem commit depois disto */ return 0; }
/* o HMI confere o tamanho da superficie antes de redireciona-la */
int ilm_surfaceSetDestinationRectangle(U id,U x,U y,U w,U h){ int k=sidx(id); if(srf[k].w!=w||srf[k].h!=h) br_logx("ilm: surfaceDest id/x|y<<16/w|h<<16",id,(x&0xffff)|(y<<16),(w&0xffff)|(h<<16)); srf[k].w=w; srf[k].h=h; return 0; }
int ilm_layerCreateWithDimension(U *id,U w,U h){ if(*id==0xffffffff||*id==0) *id=next_layer++; get(*id); br_logx("ilm: layerCreate",*id,w,h); return 0; }
static int lst(int *n,U **ids,U cnt){ U *p=(U*)malloc((cnt+1)*4); for(U i=0;i<cnt;i++) p[i]=lay[i].id; *n=cnt; *ids=p; return 0; }
int ilm_getLayerIDs(int *n,U **ids){ return lst(n,ids,nlay); }
int ilm_getSurfaceIDs(int *n,U **ids){ return lst(n,ids,0); }
int ilm_getSurfaceIDsOnLayer(U l,int *n,U **ids){ return lst(n,ids,0); }
int ilm_getPropertiesOfSurface(U id,void *p){ memset(p,0,128); { int k=sidx(id); ((U*)p)[6]=srf[k].w; ((U*)p)[7]=srf[k].h; } return 0; }
