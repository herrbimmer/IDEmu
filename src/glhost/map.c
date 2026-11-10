/* map.c: o mapa do iDrive, desenhado no host.
   No carro, o processo de navegação entrega a imagem por uma superfície do LayerManager e o HMI a usa como textura (CHmiSurfaceRedirection).
   Aqui o shim cria essa superfície (OP_MAPBIND) e este arquivo desenha nas texturas: blocos de mapa do cache em disco, posição do GPS virtual, seta do carro.
   Roda num contexto GL próprio, compartilhado com o do HMI, para não mexer no estado GL que o guest espelha aqui.
   Comandos pelo input.sock (linhas "M ..."); pedidos de bloco saem por <ctl>/map.sock e são atendidos por idemu/mapsvc.py. */
#include <math.h>
extern unsigned char *pngload(const char *path,int *w,int *h);
typedef struct { GLuint tex,fbo; u32 surf; int w,h,used; } msurf_t;
static msurf_t ms[8];
/* camada composta por baixo do HMI (mapa em tela cheia): m_lay.tex/fbo pertencem a este arquivo; c_tex/c_fbo guardam a imagem final */
static msurf_t m_lay; static int m_lv,m_lx,m_ly,m_lw,m_lh; static GLuint c_tex,c_fbo; static int c_w,c_h,c_ok;
typedef struct { int z,x,y,state; GLuint tex; unsigned last; } mtile_t;   /* state: 0 novo, 1 carregado, 2 pedido ao serviço */
#define NTILES 192
static mtile_t mt[NTILES]; static unsigned mclock;
static CGLContextObj mapctx,mainctx;
static double m_lat=-23.5505,m_lon=-46.6333,m_tlat=-23.5505,m_tlon=-46.6333,m_hdg,m_thdg; static float m_zoom=16; static int m_headup,m_night,m_dirty=1,m_pattern; static double m_last; static char m_attr[96];
static int m_sock=-1; static struct sockaddr_un m_sa; static GLuint m_prog; static int m_havepos;
static const char *m_cache(void){ const char*c=getenv("GLHOST_MAPCACHE"); return c?c:P("mapcache"); }
static void map_notify(u32 surf){ if(!replaying) input_ev(30,surf,0,0); }

static void map_request(int z,int x,int y){ if(replaying) return; if(m_sock<0){ m_sock=socket(AF_UNIX,SOCK_DGRAM,0); m_sa.sun_family=AF_UNIX; snprintf(m_sa.sun_path,sizeof m_sa.sun_path,"%s",P("map.sock")); }
  char b[64]; int n=snprintf(b,sizeof b,"%d %d %d",z,x,y); sendto(m_sock,b,n,MSG_DONTWAIT,(struct sockaddr*)&m_sa,sizeof m_sa); }
static mtile_t *tile_slot(int z,int x,int y){ mtile_t *free_=0,*old=0; for(int i=0;i<NTILES;i++){ mtile_t*t=&mt[i]; if(t->z==z&&t->x==x&&t->y==y&&(t->tex||t->state)) return t; if(!t->tex&&!t->state){ if(!free_) free_=t; } else if(!old||t->last<old->last) old=t; }
  mtile_t *t=free_?free_:old; if(t->tex){ glDeleteTextures(1,&t->tex); t->tex=0; } t->z=z;t->x=x;t->y=y;t->state=0; return t; }
/* devolve o bloco se estiver carregado; carrega do disco ou pede ao serviço (load=1) */
static mtile_t *tile_get(int z,int x,int y,int load){
  mtile_t *t=0; for(int i=0;i<NTILES;i++) if(mt[i].z==z&&mt[i].x==x&&mt[i].y==y&&(mt[i].tex||mt[i].state)){ t=&mt[i]; break; }
  if(!t){ if(!load) return 0; t=tile_slot(z,x,y); }
  t->last=++mclock; if(t->state==1) return t; if(!load) return 0;
  if(t->state==0){ char p[700]; snprintf(p,sizeof p,"%s/%d/%d/%d.png",m_cache(),z,x,y); struct stat st; if(!stat(p,&st)&&st.st_size>0){ int w,h; unsigned char*px=pngload(p,&w,&h); if(px){ glGenTextures(1,&t->tex); glBindTexture(GL_TEXTURE_2D,t->tex); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE); glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,px); free(px); t->state=1; return t; } }
    t->state=2; map_request(z,x,y); }
  return 0; }
static void lonlat_px(double lat,double lon,double zs,double *x,double *y){ double la=lat*M_PI/180; if(la>1.4844) la=1.4844; if(la<-1.4844) la=-1.4844; *x=(lon+180)/360*zs; *y=(1-log(tan(la)+1/cos(la))/M_PI)/2*zs; }
static void draw_tile_quad(double x0,double y0,double sz,float u0,float v0,float u1,float v1){ glTexCoord2f(u0,v0); glVertex2d(x0,y0); glTexCoord2f(u1,v0); glVertex2d(x0+sz,y0); glTexCoord2f(u1,v1); glVertex2d(x0+sz,y0+sz); glTexCoord2f(u0,v1); glVertex2d(x0,y0+sz); }
static void map_text(float x,float y,const char*s,void*font){ glRasterPos2f(x,y); while(*s) glutBitmapCharacter(font,*s++); }
static void map_ensure_prog(void){ if(m_prog) return; const char*fs="uniform sampler2D t;void main(){vec4 c=texture2D(t,gl_TexCoord[0].st);float l=dot(c.rgb,vec3(.3,.59,.11));vec3 d=vec3(1.0-l)*vec3(.42,.46,.52)+vec3(.03,.04,.06);gl_FragColor=vec4(mix(d,d*c.rgb*1.4,.25),1.0);}"; GLuint s=glCreateShader(GL_FRAGMENT_SHADER); glShaderSource(s,1,&fs,0); glCompileShader(s); m_prog=glCreateProgram(); glAttachShader(m_prog,s); glLinkProgram(m_prog); }
static void map_draw_surface(msurf_t *m){
  if(!m->fbo){ glGenFramebuffersEXT(1,&m->fbo); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,m->fbo); glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,m->tex,0); }
  else glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,m->fbo);
  int w=m->w,h=m->h; glViewport(0,0,w,h); glMatrixMode(GL_PROJECTION); glLoadIdentity(); if(m==&m_lay) glOrtho(0,w,h,0,-1,1); else glOrtho(0,w,0,h,-1,1); /* na textura redirecionada o HMI usa a linha 0 como topo; na camada, quem compõe é map_compose */ glMatrixMode(GL_MODELVIEW); glLoadIdentity();
  if(m_night) glClearColor(.05f,.06f,.08f,1); else glClearColor(.90f,.89f,.85f,1); glClear(GL_COLOR_BUFFER_BIT); glDisable(GL_DEPTH_TEST); glDisable(GL_BLEND);
  float zoom=m_zoom; if(w<500) zoom-=1; int iz=(int)floor(zoom); if(iz<1) iz=1; if(iz>19) iz=19; double s=pow(2,zoom-iz); double zs=(double)(1<<iz);
  double cx,cy; lonlat_px(m_lat,m_lon,zs*256,&cx,&cy);
  double rot=m_headup?m_hdg:0; double ax=w/2.0,ay=m_headup?h*0.68:h/2.0;
  glPushMatrix(); glTranslated(ax,ay,0); glRotated(-rot,0,0,1); glScaled(s,s,1); glTranslated(-cx,-cy,0);
  double rad=sqrt((double)w*w+(double)h*h)/s/2+256; int tx0=(int)floor((cx-rad)/256),tx1=(int)floor((cx+rad)/256),ty0=(int)floor((cy-rad)/256),ty1=(int)floor((cy+rad)/256); if(ty0<0) ty0=0; if(ty1>=(1<<iz)) ty1=(1<<iz)-1;
  glEnable(GL_TEXTURE_2D); glColor4f(1,1,1,1); if(m_night){ map_ensure_prog(); glUseProgram(m_prog); }
  for(int ty=ty0;ty<=ty1;ty++) for(int tx=tx0;tx<=tx1;tx++){ int wx=((tx%(1<<iz))+(1<<iz))%(1<<iz); mtile_t *t=tile_get(iz,wx,ty,1); double px=tx*256.0,py=ty*256.0;
    if(t){ glBindTexture(GL_TEXTURE_2D,t->tex); glBegin(GL_QUADS); draw_tile_quad(px,py,256,0,0,1,1); glEnd(); continue; }
    /* ainda não chegou: usa o bloco pai, ampliado */
    for(int up=1;up<=6&&iz-up>=0;up++){ int d=1<<up; mtile_t *q=tile_get(iz-up,wx>>up,ty>>up,0); if(q){ float f=1.0f/d; float u=(wx&(d-1))*f,v=(ty&(d-1))*f; glBindTexture(GL_TEXTURE_2D,q->tex); glBegin(GL_QUADS); draw_tile_quad(px,py,256,u,v,u+f,v+f); glEnd(); break; } } }
  glUseProgram(0); glDisable(GL_TEXTURE_2D);
  if(m_pattern){ glBegin(GL_LINES); glColor3f(.2f,.2f,.6f); for(int ty=ty0;ty<=ty1+1;ty++){ glVertex2d(tx0*256.0,ty*256.0); glVertex2d((tx1+1)*256.0,ty*256.0); } for(int tx=tx0;tx<=tx1+1;tx++){ glVertex2d(tx*256.0,ty0*256.0); glVertex2d(tx*256.0,(ty1+1)*256.0); } glEnd(); }
  glPopMatrix();
  /* seta do carro */
  glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA); glPushMatrix(); glTranslated(ax,ay,0); glRotated(m_hdg-rot,0,0,1); float k=w<500?.7f:1;
  glBegin(GL_TRIANGLE_FAN); glColor4f(1,1,1,1); glVertex2f(0,3*k); glVertex2f(0,-22*k); glVertex2f(15*k,17*k); glVertex2f(0,8*k); glVertex2f(-15*k,17*k); glVertex2f(0,-22*k); glEnd();
  glBegin(GL_TRIANGLE_FAN); glColor4f(.05f,.35f,.85f,1); glVertex2f(0,2*k); glVertex2f(0,-17*k); glVertex2f(11*k,13*k); glVertex2f(0,6*k); glVertex2f(-11*k,13*k); glVertex2f(0,-17*k); glEnd(); glPopMatrix();
  if(m_attr[0]&&m==&m_lay){ int tw=0; for(const char*p=m_attr;*p;p++) tw+=glutBitmapWidth(GLUT_BITMAP_HELVETICA_10,*p); glColor4f(1,1,1,.7f); glRectf(w-tw-8,h-15,w,h); glColor4f(.1f,.1f,.1f,1); map_text(w-tw-4,h-4,m_attr,GLUT_BITMAP_HELVETICA_10); }
  glDisable(GL_BLEND); }
/* Projected video (CarPlay) in IDEmu: nothing renders the phone's picture, so the CarPlay layer gets a placeholder (border, title,
   size), composed like the map: under the HMI, through the transparent hole the HMI leaves for the video. Text: "V t title|subtitle". */
static msurf_t v_lay; static int v_lv,v_lx,v_ly,v_lw,v_lh,v_dirty=1; static char v_title[96]="Apple CarPlay",v_sub[160]="emulated connection: no video from a phone";
static double wall_s(void){ struct timespec ts; clock_gettime(CLOCK_REALTIME,&ts); return ts.tv_sec+ts.tv_nsec*1e-9; }
static int text_w(const char*s,void*f){ int w=0; while(*s) w+=glutBitmapWidth(f,*s++); return w; }
/* Key codes the HMI sends to CarPlay (CarPlayControllerInput, MOST 0x24/0x70 0xCD3), as idemu/most.py forwards them: "V k <text>"
   ("V k" alone clears). The last ones are listed in a corner of the CarPlay video, over the placeholder. */
#define VK_N 10
static char v_keys[VK_N][100]; static unsigned v_nkeys; static double v_ktime; static int v_kfresh;
static void vid_key(const char*s){ if(!*s){ v_nkeys=0; return; } snprintf(v_keys[v_nkeys++%VK_N],sizeof v_keys[0],"%s",s); v_ktime=wall_s(); v_kfresh=1; }
/* the list, in a top-down projection of the video area at x0,y0 (w x h): newest at the bottom, highlighted for 1.5 s */
static void vid_keys_draw(float x0,float y0,int w,int h){ if(!v_nkeys||getenv("GLHOST_CPKEYS_OFF")) return; void*f=GLUT_BITMAP_HELVETICA_12;
  unsigned n=v_nkeys<VK_N?v_nkeys:VK_N; const float lh=15; int tw=0; char hd[48]; snprintf(hd,sizeof hd,"CarPlay key codes (%u)",v_nkeys);
  tw=text_w(hd,GLUT_BITMAP_HELVETICA_12); for(unsigned i=0;i<n;i++){ int x=text_w(v_keys[(v_nkeys-n+i)%VK_N],f); if(x>tw) tw=x; }
  float bw=tw+16, bh=(n+1)*lh+10; if(bw>w-8) bw=w-8; if(bh>h-8) bh=h-8; float bx=x0+w-bw-6, by=y0+h-bh-6;
  glDisable(GL_TEXTURE_2D); glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA); glColor4f(0,0,0,.62f); glRectf(bx,by,bx+bw,by+bh);
  glColor4f(.55f,.62f,.72f,1); map_text(bx+8,by+lh,hd,GLUT_BITMAP_HELVETICA_12);
  for(unsigned i=0;i<n;i++){ int last=i==n-1; if(last&&v_kfresh) glColor4f(.35f,.85f,1.f,1); else glColor4f(1,1,1,last?1.f:.55f+.45f*i/n); map_text(bx+8,by+(i+2)*lh,v_keys[(v_nkeys-n+i)%VK_N],f); }
  glDisable(GL_BLEND); }
static void vid_draw(void){ int w=v_lw,h=v_lh; if(!w||!h) return;
  if(!v_lay.tex||v_lay.w!=w||v_lay.h!=h){ if(!v_lay.tex) glGenTextures(1,&v_lay.tex); glBindTexture(GL_TEXTURE_2D,v_lay.tex); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR); glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,0); if(v_lay.fbo){ glDeleteFramebuffersEXT(1,&v_lay.fbo); v_lay.fbo=0; } v_lay.w=w; v_lay.h=h; }
  if(!v_lay.fbo){ glGenFramebuffersEXT(1,&v_lay.fbo); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,v_lay.fbo); glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,v_lay.tex,0); } else glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,v_lay.fbo);
  glViewport(0,0,w,h); glMatrixMode(GL_PROJECTION); glLoadIdentity(); glOrtho(0,w,h,0,-1,1); glMatrixMode(GL_MODELVIEW); glLoadIdentity(); glDisable(GL_DEPTH_TEST); glDisable(GL_TEXTURE_2D); glUseProgram(0);
  glDisable(GL_BLEND); glBegin(GL_QUADS); glColor3f(.07f,.09f,.12f); glVertex2f(0,0); glVertex2f(w,0); glColor3f(.13f,.17f,.23f); glVertex2f(w,h); glVertex2f(0,h); glEnd();
  /* frame: outer border + corner ticks, so the size and position of the video area are obvious */
  glLineWidth(3); glColor3f(.55f,.62f,.72f); glBegin(GL_LINE_LOOP); glVertex2f(2,2); glVertex2f(w-2,2); glVertex2f(w-2,h-2); glVertex2f(2,h-2); glEnd();
  glLineWidth(1); glColor3f(.35f,.42f,.52f); glBegin(GL_LINE_LOOP); glVertex2f(10,10); glVertex2f(w-10,10); glVertex2f(w-10,h-10); glVertex2f(10,h-10); glEnd();
  glLineWidth(4); glColor3f(.25f,.65f,1.f); glBegin(GL_LINES); float k=28; float cx[4]={2,w-2,w-2,2},cy[4]={2,2,h-2,h-2};
  for(int i=0;i<4;i++){ float sx=i==0||i==3?1:-1, sy=i<2?1:-1; glVertex2f(cx[i],cy[i]); glVertex2f(cx[i]+sx*k,cy[i]); glVertex2f(cx[i],cy[i]); glVertex2f(cx[i],cy[i]+sy*k); } glEnd(); glLineWidth(1);
  /* fake dock on the left, as the CarPlay home screen has: only a hint of the layout, no real UI */
  glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA); glColor4f(1,1,1,.06f); glRectf(14,14,14+h*0.16f,h-14);
  for(int i=0;i<3;i++){ float y=30+i*(h*0.16f+12), s=h*0.16f-24; glColor4f(.25f,.65f,1.f,.35f); glRectf(26,y,26+s,y+s); }
  char sz[48]; snprintf(sz,sizeof sz,"%d x %d at %d,%d",w,h,v_lx,v_ly);
  float tx=w/2.0f, ty=h/2.0f; glColor4f(1,1,1,1); map_text(tx-text_w(v_title,GLUT_BITMAP_TIMES_ROMAN_24)/2,ty-8,v_title,GLUT_BITMAP_TIMES_ROMAN_24);
  glColor4f(.75f,.82f,.9f,1); map_text(tx-text_w(v_sub,GLUT_BITMAP_HELVETICA_18)/2,ty+24,v_sub,GLUT_BITMAP_HELVETICA_18);
  glColor4f(.5f,.58f,.68f,1); map_text(tx-text_w(sz,GLUT_BITMAP_HELVETICA_12)/2,ty+50,sz,GLUT_BITMAP_HELVETICA_12);
  vid_keys_draw(0,0,w,h);
  glDisable(GL_BLEND); v_dirty=0; }
static void vid_set_layer(u32 v,u32 x,u32 y,u32 w,u32 h){ v_lv=v; v_lx=(int)x; v_ly=(int)y; v_lw=w; v_lh=h; v_dirty=1; c_ok=0; fdirty=1; if(!replaying) fprintf(stderr,"[video] camada %s %d,%d %ux%u\n",v?"visivel":"oculta",v_lx,v_ly,w,h); }
static void map_ctx_begin(void){ mainctx=CGLGetCurrentContext(); if(!mapctx){ CGLError e=CGLCreateContext(CGLGetPixelFormat(mainctx),mainctx,&mapctx); if(e){ fprintf(stderr,"[map] CGLCreateContext: %d\n",e); mapctx=0; return; } } glFlush(); CGLSetCurrentContext(mapctx); }
static void map_ctx_end(void){ glFlush(); CGLSetCurrentContext(mainctx); }
static void map_layer_draw(void){ if(!m_lw||!m_lh) return; if(!m_lay.tex||m_lay.w!=m_lw||m_lay.h!=m_lh){ if(!m_lay.tex) glGenTextures(1,&m_lay.tex); glBindTexture(GL_TEXTURE_2D,m_lay.tex); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR); glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,m_lw,m_lh,0,GL_RGBA,GL_UNSIGNED_BYTE,0); if(m_lay.fbo){ glDeleteFramebuffersEXT(1,&m_lay.fbo); m_lay.fbo=0; } m_lay.w=m_lw; m_lay.h=m_lh; } map_draw_surface(&m_lay); }
/* imagem final = mapa por baixo, HMI por cima usando o alfa que o HMI deixou na tela (o recorte do layer_mask) */
static void map_compose(void){ map_ctx_begin(); if(!mapctx) return;
  if(m_lv&&(!m_lay.tex||!m_lay.fbo)) map_layer_draw();
  if(v_lv&&(v_dirty||!v_lay.fbo)) vid_draw();
  if(!c_tex||c_w!=sw||c_h!=sh){ if(!c_tex){ glGenTextures(1,&c_tex); glGenFramebuffersEXT(1,&c_fbo); } glBindTexture(GL_TEXTURE_2D,c_tex); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR); glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR); glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,sw,sh,0,GL_RGBA,GL_UNSIGNED_BYTE,0); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,c_fbo); glFramebufferTexture2DEXT(GL_FRAMEBUFFER_EXT,GL_COLOR_ATTACHMENT0_EXT,GL_TEXTURE_2D,c_tex,0); c_w=sw; c_h=sh; }
  glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,c_fbo); glViewport(0,0,sw,sh); glMatrixMode(GL_PROJECTION); glLoadIdentity(); glOrtho(0,sw,0,sh,-1,1); glMatrixMode(GL_MODELVIEW); glLoadIdentity(); glClearColor(0,0,0,1); glClear(GL_COLOR_BUFFER_BIT); glDisable(GL_DEPTH_TEST); glDisable(GL_BLEND); glEnable(GL_TEXTURE_2D); glColor4f(1,1,1,1);
  if(m_lv){ float x0=m_lx,x1=m_lx+m_lw,y1=sh-m_ly,y0=y1-m_lh; glBindTexture(GL_TEXTURE_2D,m_lay.tex); glBegin(GL_QUADS); glTexCoord2f(0,0); glVertex2f(x0,y0); glTexCoord2f(1,0); glVertex2f(x1,y0); glTexCoord2f(1,1); glVertex2f(x1,y1); glTexCoord2f(0,1); glVertex2f(x0,y1); glEnd(); }
  if(v_lv&&v_lay.tex){ float x0=v_lx,x1=v_lx+v_lw,y1=sh-v_ly,y0=y1-v_lh; glBindTexture(GL_TEXTURE_2D,v_lay.tex); glBegin(GL_QUADS); glTexCoord2f(0,0); glVertex2f(x0,y0); glTexCoord2f(1,0); glVertex2f(x1,y0); glTexCoord2f(1,1); glVertex2f(x1,y1); glTexCoord2f(0,1); glVertex2f(x0,y1); glEnd(); }
  glEnable(GL_BLEND); glBlendFuncSeparate(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA,GL_ONE,GL_ZERO); glBindTexture(GL_TEXTURE_2D,screen_tex); glBegin(GL_QUADS); glTexCoord2f(0,0); glVertex2f(0,0); glTexCoord2f(1,0); glVertex2f(sw,0); glTexCoord2f(1,1); glVertex2f(sw,sh); glTexCoord2f(0,1); glVertex2f(0,sh); glEnd(); glDisable(GL_BLEND); glDisable(GL_TEXTURE_2D);
  c_ok=1; }
static int map_readback(unsigned char *out){ if(!(m_lv||v_lv)||!screen_tex||replaying) return 0; map_compose(); if(!c_ok||!mapctx){ return 0; } glPixelStorei(GL_PACK_ALIGNMENT,1); glReadPixels(0,0,sw,sh,GL_RGB,GL_UNSIGNED_BYTE,out); glPixelStorei(GL_PACK_ALIGNMENT,4); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,0); map_ctx_end(); return 1; }
static GLuint map_present_tex(void){ return ((m_lv||v_lv)&&c_ok)?c_tex:screen_tex; }
static void map_set_layer(u32 v,u32 x,u32 y,u32 w,u32 h){ m_lv=v; m_lx=(int)x; m_ly=(int)y; m_lw=w; m_lh=h; c_ok=0; m_dirty=1; fdirty=1; if(!replaying) fprintf(stderr,"[map] camada %s %d,%d %ux%u\n",v?"visivel":"oculta",m_lx,m_ly,w,h); }
static void map_bind(u32 surf,u32 w,u32 h){ GLint t=0; glGetIntegerv(GL_TEXTURE_BINDING_2D,&t); if(!t||!w||!h) return; glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA8,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,0);
  msurf_t *m=0; for(int i=0;i<8;i++) if(!ms[i].used){ m=&ms[i]; break; } if(!m) m=&ms[7]; if(m->fbo&&mapctx){ GLuint f=m->fbo; map_ctx_begin(); if(mapctx) glDeleteFramebuffersEXT(1,&f); map_ctx_end(); } memset(m,0,sizeof *m); m->used=1; m->tex=t; m->surf=surf; m->w=w; m->h=h; m_dirty=1; if(!replaying) fprintf(stderr,"[map] superficie 0x%x %ux%u textura %d\n",surf,w,h,t); }
static void map_forget(GLuint tex){ for(int i=0;i<8;i++) if(ms[i].used&&ms[i].tex==tex){ if(!replaying) fprintf(stderr,"[map] superficie 0x%x removida\n",ms[i].surf); GLuint f=ms[i].fbo; if(f&&mapctx){ map_ctx_begin(); if(mapctx) glDeleteFramebuffersEXT(1,&f); map_ctx_end(); } memset(&ms[i],0,sizeof ms[i]); } }
static void map_cmd(const char *l){ double a,b,c; int z,x,y; char t[96];
  if(sscanf(l,"M p %lf %lf %lf",&a,&b,&c)==3){ m_tlat=a; m_tlon=b; m_thdg=c; if(!m_havepos){ m_havepos=1; m_lat=a; m_lon=b; m_hdg=c; } m_dirty=1; }
  else if(sscanf(l,"M z %lf",&a)==1){ m_zoom=a<1?1:a>19?19:a; m_dirty=1; }
  else if(sscanf(l,"M v %d",&x)==1){ m_headup=x; m_dirty=1; }
  else if(sscanf(l,"M n %d",&x)==1){ m_night=x; m_dirty=1; }
  else if(sscanf(l,"M g %d",&x)==1){ m_pattern=x; m_dirty=1; }
  else if(sscanf(l,"M t %d %d %d",&z,&x,&y)==3){ for(int i=0;i<NTILES;i++) if(mt[i].z==z&&mt[i].x==x&&mt[i].y==y&&mt[i].state==2) mt[i].state=0; m_dirty=1; }
  else if(!strcmp(l,"M r")){ for(int i=0;i<NTILES;i++) if(mt[i].state==2) mt[i].state=0; m_dirty=1; }
  else if(!strncmp(l,"M a ",4)){ snprintf(m_attr,sizeof m_attr,"%s",l+4); m_dirty=1; }
  else if(!strncmp(l,"V k",3)&&(!l[3]||l[3]==' ')){ vid_key(l[3]?l+4:""); v_dirty=1; c_ok=0; fdirty=1; }
  else if(!strncmp(l,"V t ",4)){ const char*b=strchr(l+4,'|'); if(b){ snprintf(v_title,sizeof v_title,"%.*s",(int)(b-l-4),l+4); snprintf(v_sub,sizeof v_sub,"%s",b+1); } else snprintf(v_title,sizeof v_title,"%s",l+4); v_dirty=1; c_ok=0; fdirty=1; } }
/* chamado no laço ocioso: suaviza o movimento e redesenha só quando algo mudou (no máximo 15 vezes por segundo) */
static void map_tick(double now){ if(v_kfresh&&wall_s()-v_ktime>1.5){ v_kfresh=0; v_dirty=1; } if(v_lv&&v_dirty&&!replaying){ c_ok=0; fdirty=1; } int any=m_lv; for(int i=0;i<8;i++) if(ms[i].used) any=1; if(!any||replaying) return; if(now-m_last<0.066) return;
  double dla=m_tlat-m_lat,dlo=m_tlon-m_lon,dh=fmod(m_thdg-m_hdg+540,360)-180;
  if(fabs(dla)>2||fabs(dlo)>2){ m_lat=m_tlat; m_lon=m_tlon; dla=dlo=0; }
  if(fabs(dla)>1e-7||fabs(dlo)>1e-7||fabs(dh)>0.05){ m_lat+=dla*.15; m_lon+=dlo*.15; m_hdg=fmod(m_hdg+dh*.15+360,360); m_dirty=1; }
  { static double chk; if(now-chk>1.0){ chk=now; for(int i=0;i<NTILES;i++) if(mt[i].state==2){ char p[700]; struct stat st; snprintf(p,sizeof p,"%s/%d/%d/%d.png",m_cache(),mt[i].z,mt[i].x,mt[i].y); if(!stat(p,&st)&&st.st_size>0){ mt[i].state=0; m_dirty=1; } } } }   /* o aviso "M t" é um datagrama: se a fila encher, o bloco aparece aqui mesmo assim */
  if(!m_dirty) return; m_dirty=0; m_last=now;
  map_ctx_begin(); if(!mapctx) return; for(int i=0;i<8;i++) if(ms[i].used) map_draw_surface(&ms[i]); if(m_lv) map_layer_draw(); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT,0); map_ctx_end();
  if(m_lv) fdirty=1;
  for(int i=0;i<8;i++) if(ms[i].used) map_notify(ms[i].surf); }
