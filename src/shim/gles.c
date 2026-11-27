#include "common.h"
#define CHUNK (1024*1024)
#define GL_HALF_FLOAT 0x140B
#define GL_HALF_FLOAT_OES 0x8D61
static u32 cnt[5];            /* 0 tex,1 buf,2 fbo,3 rbo,4 obj */
static u32 unpack_align=4, pack_align=4;
static u32 cur_array_buf, cur_elem_buf, cur_fbo, cur_rbo, cur_prog, active_tex, cur_tex[32];
typedef struct { u32 en,size,type,norm,stride,vbo; const u8*ptr; } attr_t;
static attr_t at[16];
typedef struct { u32 id; u8*data; u32 size; } eb_t;
static eb_t ebs[512];
static eb_t *eb_find(u32 id,int create){
  u32 i; for(i=0;i<512;i++) if(ebs[i].id==id) return &ebs[i];
  if(!create) return 0;
  for(i=0;i<512;i++) if(!ebs[i].id){ ebs[i].id=id; return &ebs[i]; }
  return 0;
}
static u32 tsize(u32 type){ switch(type){case 0x1400:case 0x1401:return 1;case 0x1402:case 0x1403:return 2;case 0x1404:case 0x1405:case 0x1406:return 4;default:return 4;} }
static u32 pixel_components(u32 fmt){
  switch(fmt){
    case 0x1902: case 0x1906: case 0x1909: return 1;
    case 0x190A: return 2;
    case 0x1907: return 3;
    default: return 4;
  }
}
static u32 pixbpp(u32 fmt,u32 type){
  switch(type){ case 0x8363:case 0x8033:case 0x8034:return 2; case 0x1403:case 0x1402: if(fmt==0x1902||fmt==0x84F9) return 2; break; case 0x1405: case 0x84FA: return 4; }
  return pixel_components(fmt)*tsize(type);
}
static void wcopy(u32*dst,const void*src,u32 n){ memcpy(dst,src,n); if(n&3) memset((u8*)dst+n,0,4-(n&3)); }
/* ---- generic ---- */
static void gen(u32 cls,s32 n,u32*ids){
  s32 i; u32*p; if(n<=0) return;
  LOCK(); p=br_begin(OP_GEN,2+n); p[0]=cls; p[1]=n;
  for(i=0;i<n;i++){ ids[i]=++cnt[cls]; p[2+i]=ids[i]; }
  UNLOCK();
}
static void del(u32 cls,s32 n,const u32*ids){
  s32 i; u32*p; if(n<=0) return;
  LOCK(); p=br_begin(OP_DEL,2+n); p[0]=cls; p[1]=n;
  for(i=0;i<n;i++) p[2+i]=ids[i];
  UNLOCK();
}
void glGenTextures(s32 n,u32*ids){ gen(0,n,ids); }
void glGenBuffers(s32 n,u32*ids){ gen(1,n,ids); }
void glGenFramebuffers(s32 n,u32*ids){ gen(2,n,ids); }
void glGenRenderbuffers(s32 n,u32*ids){ gen(3,n,ids); }
void glDeleteTextures(s32 n,const u32*ids){ del(0,n,ids); }
void glDeleteBuffers(s32 n,const u32*ids){ s32 i; for(i=0;i<n;i++){ eb_t*e=eb_find(ids[i],0); if(e){free(e->data);e->data=0;e->size=0;e->id=0;} } del(1,n,ids); }
void glDeleteFramebuffers(s32 n,const u32*ids){ del(2,n,ids); }
void glDeleteRenderbuffers(s32 n,const u32*ids){ del(3,n,ids); }
void glDeleteShader(u32 id){ del(4,1,&id); }
void glDeleteProgram(u32 id){ del(4,1,&id); }
u32 glCreateShader(u32 type){ u32*p,id; LOCK(); id=++cnt[4]; p=br_begin(OP_CREATESHADER,2); p[0]=id; p[1]=type; UNLOCK(); return id; }
u32 glCreateProgram(void){ u32*p,id; LOCK(); id=++cnt[4]; p=br_begin(OP_CREATEPROGRAM,1); p[0]=id; UNLOCK(); return id; }
/* tracked simple */
void glActiveTexture(u32 t){ u32*p; active_tex=(t-0x84C0)&31; LOCK(); p=br_begin(OP_glActiveTexture,1); p[0]=t; UNLOCK(); }
void glBindTexture(u32 t,u32 id){ u32*p; if(t==0xDE1) cur_tex[active_tex]=id; LOCK(); p=br_begin(OP_glBindTexture,2); p[0]=t;p[1]=id; UNLOCK(); }
void glBindFramebuffer(u32 t,u32 id){ u32*p; cur_fbo=id; LOCK(); p=br_begin(OP_glBindFramebuffer,2); p[0]=t;p[1]=id; UNLOCK(); }
void glBindRenderbuffer(u32 t,u32 id){ u32*p; cur_rbo=id; LOCK(); p=br_begin(OP_glBindRenderbuffer,2); p[0]=t;p[1]=id; UNLOCK(); }
void glUseProgram(u32 id){ u32*p; cur_prog=id; LOCK(); p=br_begin(OP_glUseProgram,1); p[0]=id; UNLOCK(); }
void glBindBuffer(u32 t,u32 id){ u32*p; if(t==0x8892) cur_array_buf=id; else if(t==0x8893) cur_elem_buf=id; LOCK(); p=br_begin(OP_glBindBuffer,2); p[0]=t;p[1]=id; UNLOCK(); }
void glPixelStorei(u32 pn,u32 v){ u32*p; if(pn==0xCF5) unpack_align=v; else if(pn==0xD05) pack_align=v; LOCK(); p=br_begin(OP_glPixelStorei,2); p[0]=pn;p[1]=v; UNLOCK(); }
void glEnableVertexAttribArray(u32 i){ u32*p; if(i<16) at[i].en=1; LOCK(); p=br_begin(OP_glEnableVertexAttribArray,1); p[0]=i; UNLOCK(); }
void glDisableVertexAttribArray(u32 i){ u32*p; if(i<16) at[i].en=0; LOCK(); p=br_begin(OP_glDisableVertexAttribArray,1); p[0]=i; UNLOCK(); }
void glFinish(void){ LOCK(); br_flush(); UNLOCK(); }
void glFlush(void){ glFinish(); }
/* ---- buffers ---- */
void glBufferSubData(u32 target,s32 off,s32 size,const void*data){
  s32 done=0;
  if(target==0x8893){ eb_t*e=eb_find(cur_elem_buf,1); if(e&&e->data&&(u32)(off+size)<=e->size) memcpy(e->data+off,data,size); }
  while(done<size){ s32 n=size-done; u32*p; if(n>CHUNK) n=CHUNK;
    LOCK(); p=br_begin(OP_BUFFERSUBDATA,3+(n+3)/4); p[0]=target;p[1]=off+done;p[2]=n; wcopy(p+3,(const u8*)data+done,n); UNLOCK(); done+=n; }
}
void glBufferData(u32 target,s32 size,const void*data,u32 usage){
  u32*p;
  if(target==0x8893){ eb_t*e=eb_find(cur_elem_buf,1); if(e){ free(e->data); e->data=(u8*)malloc(size?size:1); e->size=size; if(data) memcpy(e->data,data,size); else memset(e->data,0,size);} }
  LOCK(); p=br_begin(OP_BUFFERDATA,3); p[0]=target;p[1]=size;p[2]=usage; UNLOCK();   /* allocate */
  if(data&&size>0){ s32 done=0; while(done<size){ s32 n=size-done; if(n>CHUNK)n=CHUNK;
    LOCK(); p=br_begin(OP_BUFFERSUBDATA,3+(n+3)/4); p[0]=target;p[1]=done;p[2]=n; wcopy(p+3,(const u8*)data+done,n); UNLOCK(); done+=n; } }
}
/* ---- textures ---- */
static u32 texture_type(u32 type){
  return type==GL_HALF_FLOAT_OES ? GL_HALF_FLOAT : type;
}
static u32 texture_bpp(u32 fmt,u32 type){
  if(type!=GL_HALF_FLOAT) return pixbpp(fmt,type);
  switch(fmt){
    case 0x1903: return 2; /* GL_RED */
    case 0x8227: return 4; /* GL_RG */
    default: return 2*pixel_components(fmt);
  }
}
static u32 unpack_stride(u32 row_bytes){
  return (row_bytes+unpack_align-1)/unpack_align*unpack_align;
}
void glTexSubImage2D(u32 target,s32 level,s32 x,s32 y,s32 w,s32 h,u32 fmt,u32 type,const void*pix){
  if(!pix||w<=0||h<=0) return;
  type=texture_type(type);
  u32 row_bytes=w*texture_bpp(fmt,type), stride=unpack_stride(row_bytes);
  s32 rows_per=(CHUNK*2)/(stride?stride:1);
  if(rows_per<1) rows_per=1;
  for(s32 done=0;done<h;){
    s32 rows=h-done;
    if(rows>rows_per) rows=rows_per;
    /* Unpack alignment governs the gaps between rows. */
    u32 bytes=(rows-1)*stride+row_bytes;
    LOCK();
    u32 *p=br_begin(OP_TEXSUBIMAGE,9+(bytes+3)/4);
    p[0]=target;p[1]=level;p[2]=x;p[3]=y+done;p[4]=w;p[5]=rows;p[6]=fmt;p[7]=type;p[8]=bytes;
    wcopy(p+9,(const u8*)pix+(u32)done*stride,bytes);
    UNLOCK();
    done+=rows;
  }
}
void glTexImage2D(u32 target,s32 level,s32 ifmt,s32 w,s32 h,s32 border,u32 fmt,u32 type,const void*pix){
  type=texture_type(type);
  u64 span=0;
  if(pix&&w>0&&h>0){
    u32 row_bytes=w*texture_bpp(fmt,type);
    span=(u64)(h-1)*unpack_stride(row_bytes)+row_bytes;
  }
  u32 bytes=span<=CHUNK*2 ? (u32)span : 0;
  LOCK();
  u32 *p=br_begin(OP_TEXIMAGE,10+(bytes+3)/4);
  p[0]=target;p[1]=level;p[2]=ifmt;p[3]=w;p[4]=h;p[5]=border;p[6]=fmt;p[7]=type;p[8]=bytes!=0;p[9]=bytes;
  if(bytes) wcopy(p+10,pix,bytes);
  UNLOCK();
  if(span>CHUNK*2) glTexSubImage2D(target,level,0,0,w,h,fmt,type,pix);
}
/* ---- shaders ---- */
void glShaderSource(u32 sh,s32 count,const char*const*str,const s32*len){
  s32 i; u32 tot=0; u32*p; u8*d;
  for(i=0;i<count;i++) tot+= (len&&len[i]>=0)?(u32)len[i]:(u32)strlen(str[i]);
  LOCK(); p=br_begin(OP_SHADERSOURCE,2+(tot+3)/4); p[0]=sh;p[1]=tot; d=(u8*)(p+2);
  for(i=0;i<count;i++){ u32 l=(len&&len[i]>=0)?(u32)len[i]:(u32)strlen(str[i]); memcpy(d,str[i],l); d+=l; }
  if(tot&3) memset(d,0,4-(tot&3));
  UNLOCK();
}
void glShaderBinary(s32 n,const u32*sh,u32 fmt,const void*bin,s32 len){ s32 i; u32*p; LOCK(); for(i=0;i<n;i++){ p=br_begin(OP_SHADERBIN,2+(len+3)/4); p[0]=sh[i]; p[1]=len; memcpy(p+2,bin,len); } UNLOCK(); }
/* ---- uniforms ---- */
static void unif(s32 loc,s32 count,u32 vec,u32 isint,const void*v){
  u32 nw=count*vec; u32*p; if(count<=0) return;
  LOCK(); p=br_begin(OP_UNIFORMV,4+nw); p[0]=loc;p[1]=count;p[2]=vec;p[3]=isint; memcpy(p+4,v,nw*4); UNLOCK();
}
void glUniform1fv(s32 l,s32 c,const void*v){unif(l,c,1,0,v);} void glUniform2fv(s32 l,s32 c,const void*v){unif(l,c,2,0,v);}
void glUniform3fv(s32 l,s32 c,const void*v){unif(l,c,3,0,v);} void glUniform4fv(s32 l,s32 c,const void*v){unif(l,c,4,0,v);}
void glUniform1iv(s32 l,s32 c,const void*v){unif(l,c,1,1,v);} void glUniform2iv(s32 l,s32 c,const void*v){unif(l,c,2,1,v);}
void glUniform3iv(s32 l,s32 c,const void*v){unif(l,c,3,1,v);} void glUniform4iv(s32 l,s32 c,const void*v){unif(l,c,4,1,v);}
static void umat(s32 loc,s32 count,u32 tr,u32 dim,const void*v){
  u32 nw=count*dim*dim; u32*p; if(count<=0) return;
  LOCK(); p=br_begin(OP_UNIFORMMATRIX,4+nw); p[0]=loc;p[1]=count;p[2]=dim;p[3]=tr; memcpy(p+4,v,nw*4); UNLOCK();
}
void glUniformMatrix2fv(s32 l,s32 c,u32 t,const void*v){umat(l,c,t,2,v);} void glUniformMatrix3fv(s32 l,s32 c,u32 t,const void*v){umat(l,c,t,3,v);}
void glUniformMatrix4fv(s32 l,s32 c,u32 t,const void*v){umat(l,c,t,4,v);}
/* ---- attribs / draw ---- */
void glVertexAttribPointer(u32 idx,s32 size,u32 type,u32 norm,s32 stride,const void*ptr){
  u32*p; if(idx>=16) return;
  at[idx].size=size;at[idx].type=type;at[idx].norm=norm;at[idx].stride=stride;at[idx].vbo=cur_array_buf;at[idx].ptr=(const u8*)ptr;
  if(!cur_array_buf) return;
  LOCK(); p=br_begin(OP_ATTRIBPTR,6); p[0]=idx;p[1]=size;p[2]=type;p[3]=norm;p[4]=stride;p[5]=(u32)ptr; UNLOCK();
}
static void send_client_attribs(u32 first,u32 count){
  u32 i;
  for(i=0;i<16;i++){ attr_t*a=&at[i]; if(!a->en||a->vbo||!a->ptr) continue;
    u32 es=a->size*tsize(a->type); u32 st=a->stride?a->stride:es; u32 len=(first+count-1)*st+es; u32*p;
    if(count==0) continue;
    LOCK(); p=br_begin(OP_CLIENTATTRIB,7+(len+3)/4); p[0]=i;p[1]=a->size;p[2]=a->type;p[3]=a->norm;p[4]=a->stride;p[5]=len;p[6]=0; wcopy(p+7,a->ptr,len); UNLOCK(); }
}
void glDrawArrays(u32 mode,s32 first,s32 count){
  u32*p; send_client_attribs(first,count);
  LOCK(); p=br_begin(OP_DRAWARRAYS,3); p[0]=mode;p[1]=first;p[2]=count; UNLOCK();
}
void glDrawElements(u32 mode,s32 count,u32 type,const void*idx){
  u32*p; u32 ts=tsize(type); u32 i,mx=0; int anyc=0;
  for(i=0;i<16;i++) if(at[i].en&&!at[i].vbo&&at[i].ptr) anyc=1;
  if(anyc){
    if(cur_elem_buf){ eb_t*e=eb_find(cur_elem_buf,0); const u8*b=e&&e->data?e->data+(u32)idx:0; if(b&&(u32)idx+count*ts<=e->size)
      for(i=0;i<(u32)count;i++){ u32 v= ts==1?b[i]: ts==2?((const u16*)b)[i]:((const u32*)b)[i]; if(v>mx)mx=v; } else mx=65535; }
    else { const u8*b=(const u8*)idx; for(i=0;i<(u32)count;i++){ u32 v= ts==1?b[i]: ts==2?((const u16*)b)[i]:((const u32*)b)[i]; if(v>mx)mx=v; } }
    send_client_attribs(0,mx+1);
  }
  if(cur_elem_buf){ LOCK(); p=br_begin(OP_DRAWELEMENTS,5); p[0]=mode;p[1]=count;p[2]=type;p[3]=0;p[4]=(u32)idx; UNLOCK(); }
  else { u32 n=count*ts; LOCK(); p=br_begin(OP_DRAWELEMENTS,5+(n+3)/4); p[0]=mode;p[1]=count;p[2]=type;p[3]=1;p[4]=n; wcopy(p+5,idx,n); UNLOCK(); }
}
/* ---- queries (sync) ---- */
static u32 *rep;
static s32 str_copy(char*dst,s32 max,const u8*src,u32 n,s32*outlen){
  s32 l=(s32)n; if(max<=0){ if(outlen)*outlen=0; return 0; } if(l>max-1) l=max-1; memcpy(dst,src,l); dst[l]=0; if(outlen)*outlen=l; return l; }
s32 glGetUniformLocation(u32 prog,const char*name){
  u32 l=strlen(name),*p; s32 r=-1; u32 n;
  LOCK(); p=br_begin(OP_GETUNILOC,2+(l+3)/4); p[0]=prog;p[1]=l; wcopy(p+2,name,l); n=br_sync(&rep); if(n>=4) r=(s32)rep[0]; UNLOCK(); return r; }
s32 glGetAttribLocation(u32 prog,const char*name){
  u32 l=strlen(name),*p; s32 r=-1; u32 n;
  LOCK(); p=br_begin(OP_GETATTRLOC,2+(l+3)/4); p[0]=prog;p[1]=l; wcopy(p+2,name,l); n=br_sync(&rep); if(n>=4) r=(s32)rep[0]; UNLOCK(); return r; }
void glGetShaderiv(u32 sh,u32 pn,s32*out){ u32*p,n; LOCK(); p=br_begin(OP_GETSHADERIV,2); p[0]=sh;p[1]=pn; n=br_sync(&rep); *out=n>=4?(s32)rep[0]:(pn==0x8B81?1:0); UNLOCK(); }
void glGetProgramiv(u32 pr,u32 pn,s32*out){ u32*p,n; LOCK(); p=br_begin(OP_GETPROGRAMIV,2); p[0]=pr;p[1]=pn; n=br_sync(&rep); *out=n>=4?(s32)rep[0]:(pn==0x8B82?1:0); UNLOCK(); }
static void getlog(u32 op,u32 id,s32 max,s32*len,char*log){ u32*p,n; LOCK(); p=br_begin(op,1); p[0]=id; n=br_sync(&rep); if(n>=0) str_copy(log,max,(const u8*)rep,n,len); UNLOCK(); }
void glGetShaderInfoLog(u32 s,s32 max,s32*len,char*log){ getlog(OP_SHADERLOG,s,max,len,log); }
void glGetProgramInfoLog(u32 s,s32 max,s32*len,char*log){ getlog(OP_PROGRAMLOG,s,max,len,log); }
static void getactive(u32 which,u32 prog,u32 idx,s32 max,s32*len,s32*size,u32*type,char*name){
  u32*p,n; LOCK(); p=br_begin(OP_GETACTIVE,3); p[0]=which;p[1]=prog;p[2]=idx; n=br_sync(&rep);
  if(n>=12){ if(size)*size=rep[0]; if(type)*type=rep[1]; str_copy(name,max,(const u8*)(rep+3),n-12,len); } else { if(len)*len=0; if(size)*size=1; if(type)*type=0x8B50; if(max>0)name[0]=0; }
  UNLOCK(); }
void glGetActiveAttrib(u32 pr,u32 i,s32 max,s32*len,s32*size,u32*type,char*name){ getactive(0,pr,i,max,len,size,type,name); }
void glGetActiveUniform(u32 pr,u32 i,s32 max,s32*len,s32*size,u32*type,char*name){ getactive(1,pr,i,max,len,size,type,name); }
void glGetAttachedShaders(u32 pr,s32 max,s32*cnt,u32*sh){ u32*p,n; s32 i,c=0; LOCK(); p=br_begin(OP_GETATTACHED,2); p[0]=pr;p[1]=max; n=br_sync(&rep); if(n>=4){ c=rep[0]; if(c>max)c=max; for(i=0;i<c;i++) sh[i]=rep[1+i]; } if(cnt)*cnt=c; UNLOCK(); }
u32 glCheckFramebufferStatus(u32 t){ u32*p,n,r=0x8CD5; LOCK(); p=br_begin(OP_CHECKFB,1); p[0]=t; n=br_sync(&rep); if(n>=4) r=rep[0]; UNLOCK(); return r; }
static u32 i2f(u32 v){ u32 e=0,m; if(!v) return 0; m=v; while(m>=2){m>>=1;e++;} /* v<2^24 assumed */ return ((127+e)<<23)|(((v<<(23-e))&0x7fffff)); }
static u32 pn_count(u32 pn){ switch(pn){ case 0xBA2:case 0xC10:case 0xC22:case 0xC23:case 0x8005:return 4; case 0x846E:case 0x846D:case 0xB70:case 0xD3A:return 2; default:return 1; } }
static int es_local(u32 pn,s32*v){
  switch(pn){ case 0x8DF9:case 0x86A2:*v=0;return 1; case 0x8DFA:*v=1;return 1; case 0x8DFB:case 0x8DFD:*v=256;return 1; case 0x8DFC:*v=8;return 1;
   case 0x8B9A:*v=0x1401;return 1; case 0x8B9B:*v=0x1908;return 1;
   case 0x8CA6:*v=cur_fbo;return 1; case 0x8CA7:*v=cur_rbo;return 1; case 0x8B8D:*v=cur_prog;return 1; case 0x8894:*v=cur_array_buf;return 1; case 0x8895:*v=cur_elem_buf;return 1; case 0x8069:*v=cur_tex[active_tex];return 1; case 0x84E0:*v=0x84C0+active_tex;return 1; }
  return 0; }
static void getv(u32 pn,u32 kind,void*out){
  u32 i,n,c,*p; s32 v;
  if(es_local(pn,&v)){ if(kind==1){ ((u32*)out)[0]=i2f((u32)v); } else if(kind==2){ ((u8*)out)[0]=v?1:0; } else { ((s32*)out)[0]=v; } return; }
  c=pn_count(pn); LOCK(); p=br_begin(OP_GETINTEGERV,2); p[0]=pn;p[1]=kind; n=br_sync(&rep);
  for(i=0;i<c&&i*4<n;i++){ if(kind==2) ((u8*)out)[i]=rep[i]?1:0; else ((u32*)out)[i]=rep[i]; }
  UNLOCK(); }
void glGetIntegerv(u32 pn,s32*out){ getv(pn,0,out); }
void glGetFloatv(u32 pn,void*out){ getv(pn,1,out); }
void glGetBooleanv(u32 pn,void*out){ getv(pn,2,out); }
u32 glGetError(void){ return 0; }
const u8 *glGetString(u32 name){
  switch(name){ case 0x1F00:return (const u8*)"Imagination Technologies"; case 0x1F01:return (const u8*)"PowerVR SGX 544MP";
   case 0x1F02:return (const u8*)"OpenGL ES 2.0 build 1.10@2359963"; case 0x8B8C:return (const u8*)"OpenGL ES GLSL ES 1.00";
   case 0x1F03:return (const u8*)"GL_OES_texture_npot GL_OES_depth24 GL_OES_rgb8_rgba8 GL_OES_standard_derivatives GL_OES_vertex_half_float GL_OES_element_index_uint GL_OES_packed_depth_stencil GL_IMG_texture_format_BGRA8888 GL_EXT_texture_format_BGRA8888 GL_EXT_blend_minmax GL_OES_mapbuffer_dummy"; }
  return (const u8*)""; }
void glReadPixels(s32 x,s32 y,s32 w,s32 h,u32 fmt,u32 type,void*pix){
  u32*p,n; u32 bpp=pixbpp(fmt,type); u32 row=(w*bpp+pack_align-1)/pack_align*pack_align;
  LOCK(); p=br_begin(OP_READPIXELS,7); p[0]=x;p[1]=y;p[2]=w;p[3]=h;p[4]=fmt;p[5]=type;p[6]=row; n=br_sync(&rep);
  if(n>=row*h) memcpy(pix,rep,row*h); else memset(pix,0,row*h); UNLOCK(); }
/* stubs for ES calls not forwarded */
#include "gen_stub.c"
