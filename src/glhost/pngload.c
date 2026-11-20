/* pngload.c: decode a cached map image to RGBA. */
#include <stdlib.h>
#include <string.h>
#ifdef __APPLE__
#include <ApplicationServices/ApplicationServices.h>
unsigned char *pngload(const char *path,int *w,int *h){
  CFStringRef s=CFStringCreateWithCString(0,path,kCFStringEncodingUTF8); if(!s) return 0;
  CFURLRef u=CFURLCreateWithFileSystemPath(0,s,kCFURLPOSIXPathStyle,0); CFRelease(s); if(!u) return 0;
  CGImageSourceRef src=CGImageSourceCreateWithURL(u,0); CFRelease(u); if(!src) return 0;
  CGImageRef img=CGImageSourceCreateImageAtIndex(src,0,0); CFRelease(src); if(!img) return 0;
  int W=(int)CGImageGetWidth(img),H=(int)CGImageGetHeight(img);
  unsigned char *px=calloc(1,(size_t)W*H*4);
  CGColorSpaceRef cs=CGColorSpaceCreateDeviceRGB();
  CGContextRef c=px?CGBitmapContextCreate(px,W,H,8,(size_t)W*4,cs,kCGImageAlphaPremultipliedLast):0;
  if(c){ CGContextDrawImage(c,CGRectMake(0,0,W,H),img); CGContextRelease(c); } else { free(px); px=0; }
  CGColorSpaceRelease(cs); CGImageRelease(img); *w=W; *h=H; return px; }
#else
#include <png.h>
unsigned char *pngload(const char *path,int *w,int *h){
  FILE *f=fopen(path,"rb"); if(!f) return 0;
  png_structp png=png_create_read_struct(PNG_LIBPNG_VER_STRING,0,0,0);
  png_infop info=png?png_create_info_struct(png):0;
  if(!info){ if(png) png_destroy_read_struct(&png,0,0); fclose(f); return 0; }
  unsigned char *volatile px=0; png_bytep *volatile rows=0;
  if(setjmp(png_jmpbuf(png))){ free(rows); free(px); png_destroy_read_struct(&png,&info,0); fclose(f); return 0; }
  png_init_io(png,f); png_read_info(png,info);
  png_set_strip_16(png); png_set_palette_to_rgb(png); png_set_expand_gray_1_2_4_to_8(png);
  if(png_get_valid(png,info,PNG_INFO_tRNS)) png_set_tRNS_to_alpha(png);
  int color=png_get_color_type(png,info);
  if(color==PNG_COLOR_TYPE_GRAY||color==PNG_COLOR_TYPE_GRAY_ALPHA) png_set_gray_to_rgb(png);
  if(!(color&PNG_COLOR_MASK_ALPHA)&&!png_get_valid(png,info,PNG_INFO_tRNS)) png_set_add_alpha(png,0xff,PNG_FILLER_AFTER);
  png_read_update_info(png,info);
  int W=(int)png_get_image_width(png,info),H=(int)png_get_image_height(png,info);
  if(W<=0||H<=0||png_get_channels(png,info)!=4||(size_t)W>(size_t)-1/((size_t)H*4)){ png_destroy_read_struct(&png,&info,0); fclose(f); return 0; }
  px=malloc((size_t)W*H*4); rows=px?malloc((size_t)H*sizeof(*rows)):0;
  if(!rows){ free(px); png_destroy_read_struct(&png,&info,0); fclose(f); return 0; }
  for(int y=0;y<H;y++) rows[y]=px+(size_t)y*W*4;
  png_read_image(png,rows); png_read_end(png,0); free(rows); png_destroy_read_struct(&png,&info,0); fclose(f);
  *w=W; *h=H; return px;
}
#endif
