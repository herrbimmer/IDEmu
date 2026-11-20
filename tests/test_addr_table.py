"""Run the guest address-table parser with host-side file mocks."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
static const char *payload;
static unsigned offset, opens, overrides, invalids;
static int read_failure, open_failure=2;
int *__get_errno_ptr(void){ return &open_failure; }
static int test_open(const char *path,int flags,...){
  assert(!strcmp(path,"/fs/shim/addr.tab")); opens++; offset=0; return payload?3:-1;
}
static long test_read(int fd,void *out,unsigned long size){
  if(read_failure) return -1;
  unsigned long n=strlen(payload)-offset; if(n>size)n=size;
  memcpy(out,payload+offset,n); offset+=n; return n;
}
static int test_close(int fd){ return 0; }
void br_log(const char *s){ invalids++; }
void br_logx(const char *s,unsigned a,unsigned b,unsigned c){ overrides=a; }
#define open test_open
#define read test_read
#define close test_close
#include "hook.c"
#ifndef HMI_PROFILE_1803
static unsigned defaults[29];
static void rejected(const char *text){
  memcpy(&AD,defaults,sizeof AD); payload=text; overrides=invalids=0;
  assert(addr_load()==-1);
  assert(!memcmp(&AD,defaults,sizeof AD));
  assert(!overrides && invalids==1);
}
#endif
int main(void){
#ifdef HMI_PROFILE_1803
  payload="setup_screen_registered 0x1000\n";
  assert(addr_load()==0);
  assert(!opens);
  assert(HMI_ADDR(setup_screen_registered,A_STC)==0x2f00ac);
  assert(PROFILE_CHECK==1 && W0_STC==0xe3710008);
  assert(!HMI_FEATURE_TOUCH && !HMI_FEATURE_TPM && !HMI_FEATURE_DEBUG);
#else
  memcpy(defaults,&AD,sizeof AD);
  assert(addr_load()==0);
  assert(opens==1 && !memcmp(&AD,defaults,sizeof AD) && !invalids);
  char table[4096],bad[8193],*p=table;
  for(unsigned i=0;i<29;i++)p+=sprintf(p,"%s 0x%x\n",AD_NAME[i],0x1000+i*4);
  payload=table; assert(addr_load()==0);
  assert(overrides==29);
  for(unsigned i=0;i<29;i++)assert(((unsigned*)&AD)[i]==0x1000+i*4);
  assert(HMI_ADDR(setup_screen_registered,A_STC)==0x101c);
  rejected("setup_screen_registered 0x1000\n");
  strcpy(bad,table); bad[strlen(bad)-1]=0; rejected(bad);
  strcpy(bad,table); strcat(bad,"setup_screen_registered 0x1000\n"); rejected(bad);
  strcpy(bad,table); strcat(bad,"unknown_hook 0x1000\n"); rejected(bad);
  strcpy(bad,table); strstr(bad,"0x")[2]='g'; rejected(bad);
  strcpy(bad,table); strstr(bad,"0x")[2]='0'; rejected(bad);
  strcpy(bad,table); strstr(bad,"0x")[5]='1'; rejected(bad);
  sprintf(bad,"%s 0x100000000\n%s",AD_NAME[0],strchr(table,'\n')+1); rejected(bad);
  memset(bad,' ',8192); bad[8192]=0; rejected(bad);
  read_failure=1; rejected(table);
  read_failure=0; open_failure=13; rejected(NULL);
#endif
  return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang is needed for the guest C parser self-check")
class AddressTableTest(unittest.TestCase):
    def test_complete_tables_and_profile_isolation(self):
        source_dir = Path(__file__).resolve().parents[1] / "src" / "shim"
        linker_flag = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
        with tempfile.TemporaryDirectory() as tmp:
            source, executable = Path(tmp) / "check.c", Path(tmp) / "check"
            source.write_text(HARNESS)
            for profile in ("default", "1803"):
                with self.subTest(profile=profile):
                    command = ["clang", "-w", "-D_FORTIFY_SOURCE=0", "-ffunction-sections",
                               "-fdata-sections", linker_flag, "-I", str(source_dir)]
                    if profile == "1803":
                        command.append("-DHMI_PROFILE_1803=1")
                    result = subprocess.run(command + [str(source), "-o", str(executable)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
