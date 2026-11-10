# Generates guest stub (gen_stub.c), host dispatch (gen_host.inc), shared ops (glops.h)
SIMPLE=[
('glActiveTexture','i'),('glBlendColor','ffff'),('glBlendEquationSeparate','ii'),('glBlendFuncSeparate','iiii'),
('glClear','i'),('glClearColor','ffff'),('glClearDepthf','f'),('glClearStencil','i'),('glColorMask','iiii'),
('glCullFace','i'),('glDepthFunc','i'),('glDepthMask','i'),('glDisable','i'),('glEnable','i'),('glFrontFace','i'),
('glLineWidth','f'),('glPolygonOffset','ff'),('glSampleCoverage','fi'),('glScissor','iiii'),('glViewport','iiii'),
('glStencilFuncSeparate','iiii'),('glStencilMaskSeparate','ii'),('glStencilOpSeparate','iiii'),
('glVertexAttrib4f','iffff'),('glTexParameteri','iii'),('glTexParameterf','iif'),
('glCopyTexSubImage2D','iiiiiiii'),('glGenerateMipmap','i'),
('glBindBuffer','iB'),('glBindFramebuffer','iF'),('glBindRenderbuffer','iR'),('glBindTexture','iT'),
('glUseProgram','O'),('glAttachShader','OO'),('glDetachShader','OO'),('glCompileShader','O'),('glLinkProgram','O'),
('glFramebufferRenderbuffer','iiiR'),('glFramebufferTexture2D','iiiTi'),('glRenderbufferStorage','iiii'),
('glPixelStorei','ii'),('glEnableVertexAttribArray','i'),('glDisableVertexAttribArray','i'),
]
NOSTUB={'glPixelStorei','glEnableVertexAttribArray','glDisableVertexAttribArray','glBindBuffer','glActiveTexture','glBindTexture','glBindFramebuffer','glBindRenderbuffer','glUseProgram'}
HOSTX={
 'glClearDepthf':'glClearDepth((double)F(a[0]))',
 'glGenerateMipmap':'glGenerateMipmapEXT(a[0])',
 'glBindFramebuffer':'glBindFramebufferEXT(a[0], H(2,a[1]))',
 'glBindRenderbuffer':'glBindRenderbufferEXT(a[0], H(3,a[1]))',
 'glFramebufferRenderbuffer':'fb_renderbuffer(a[0],a[1],a[2],a[3])',
 'glFramebufferTexture2D':'glFramebufferTexture2DEXT(a[0],a[1],a[2],H(0,a[3]),a[4])',
 'glRenderbufferStorage':'rb_storage(a[0],a[1],a[2],a[3])',
 'glSampleCoverage':'glSampleCoverage(F(a[0]),(GLboolean)a[1])',
 'glBindBuffer':'do_bindbuffer(a[0],H(1,a[1]))',
 'glDepthMask':'glDepthMask((GLboolean)a[0])',
 'glColorMask':'glColorMask(a[0],a[1],a[2],a[3])',
 'glBindTexture':'glBindTexture(TEXT(a[0]),H(0,a[1]))',
 'glUseProgram':'glUseProgram(H(4,a[0]))',
 'glAttachShader':'do_attach(a[0],a[1])',
 'glDetachShader':'do_detach(a[0],a[1])',
 'glCompileShader':'do_compile(a[0])',
 'glLinkProgram':'do_link(a[0])',
 'glTexParameteri':'do_texparam(a[0],a[1],(int)a[2])',
 'glTexParameterf':'do_texparam(a[0],a[1],(int)F(a[2]))',
}
HAND=['GEN','DEL','CREATESHADER','CREATEPROGRAM','BUFFERDATA','BUFFERSUBDATA','TEXIMAGE','TEXSUBIMAGE','SHADERSOURCE',
 'UNIFORMV','UNIFORMMATRIX','ATTRIBPTR','CLIENTATTRIB','DRAWARRAYS','DRAWELEMENTS','GETUNILOC','GETATTRLOC','GETSHADERIV','GETPROGRAMIV',
 'SHADERLOG','PROGRAMLOG','GETACTIVE','GETINTEGERV','READPIXELS','CHECKFB','GETATTACHED','SWAP','LOG','SETCTX','FINISH','GETERRORS','SHADERBIN','GETINPUT','MAPBIND','MAPLAYER','VIDLAYER']
ops=[n for n,_ in SIMPLE]+['OP_'+h for h in HAND]
with open('glops.h','w') as f:
    f.write('enum {\n')
    for i,n in enumerate(ops,1): f.write('  %s = %d,\n'%(n if n.startswith('OP_') else 'OP_'+n,i))
    f.write('};\n')
with open('gen_stub.c','w') as f:
    for n,sig in SIMPLE:
        if n in NOSTUB: continue
        args=','.join('u32 a%d'%i for i in range(len(sig)))
        f.write('void %s(%s){ u32*p; LOCK(); p=br_begin(OP_%s,%d);'%(n,args or 'void',n,len(sig)))
        for i in range(len(sig)): f.write(' p[%d]=a%d;'%(i,i))
        f.write(' UNLOCK(); }\n')
    f.write('typedef struct{const char*n;void*p;}fent;\nconst fent gl_funcs[]={\n')
    for n,_ in SIMPLE: f.write(' {"%s",(void*)%s},\n'%(n,n))
    f.write('#include "gl_hand_names.inc"\n {0,0}};\n')
with open('gen_host.inc','w') as f:
    for n,sig in SIMPLE:
        if n in HOSTX: x=HOSTX[n]
        else:
            ar=[]
            for i,c in enumerate(sig):
                if c=='i': ar.append('a[%d]'%i)
                elif c=='f': ar.append('F(a[%d])'%i)
                else: ar.append('H(%d,a[%d])'%({'T':0,'B':1,'F':2,'R':3,'O':4}[c],i))
            x='%s(%s)'%(n,','.join(ar))
        f.write('case OP_%s: %s; break;\n'%(n,x))
open('opnames.inc','w').write(''.join('"%s",\n'%(n if n.startswith('OP_') else n) for n in ['NONE']+ops))
print(len(SIMPLE),'simple ops;',len(ops),'total')
