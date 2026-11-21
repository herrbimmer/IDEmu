"""Native Screen windows must fail safely until buffer posting is supported."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HARNESS = r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static int guest_errno;
static unsigned unsupported;
int *__get_errno_ptr(void){ return &guest_errno; }
void br_logx(const char *s,unsigned a,unsigned b,unsigned c){
  if(!strcmp(s,"screen_create_window_type: unsupported")) unsupported++;
}
#include "egl.c"
int main(void){
  void *ctx=0;
  assert(!screen_create_context(&ctx,0) && ctx);
  /* Model VideoManager and VolOSD's error branch: no handle may escape to the
     unavailable context/display/buffer APIs after a typed-window request. */
  int types[]={0,1,-1,0x7fffffff};
  for(unsigned i=0;i<sizeof(types)/sizeof(types[0]);i++){
    void *win=ctx;
    guest_errno=0;
    assert(screen_create_window_type(&win,ctx,types[i])==-1);
    assert(!win && guest_errno==89);
  }
  guest_errno=0;
  assert(screen_create_window_type(NULL,NULL,0)==-1 && guest_errno==89);
  assert(unsupported==5);
  /* The existing EGL window path still creates a usable shim object. */
  void *legacy=0;
  assert(!screen_create_window(&legacy,ctx) && legacy);
  assert(((obj_t*)legacy)->kind==K_WIN);
  assert(((obj_t*)legacy)->w==1920 && ((obj_t*)legacy)->h==720);
  free(legacy);
  free(ctx);
  return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang is needed for the Screen shim check")
class ScreenWindowTypeTest(unittest.TestCase):
    def test_native_window_refusal_preserves_egl_path(self):
        source_dir = Path(__file__).resolve().parents[1] / "src" / "shim"
        linker_flag = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
        with tempfile.TemporaryDirectory() as tmp:
            source, executable = Path(tmp) / "check.c", Path(tmp) / "check"
            source.write_text(HARNESS)
            command = ["clang", "-w", "-D_FORTIFY_SOURCE=0", "-fsanitize=address",
                       "-ffunction-sections", "-fdata-sections", linker_flag,
                       "-I", str(source_dir), str(source), "-o", str(executable)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
