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
#ifndef HMI_PROFILE_FIXED
static unsigned defaults[29];
static void rejected(const char *text){
  memcpy(&AD,defaults,sizeof AD); payload=text; overrides=invalids=0;
  assert(addr_load()==-1);
  assert(!memcmp(&AD,defaults,sizeof AD));
  assert(!overrides && invalids==1);
}
#endif
#ifdef HMI_PROFILE_006016
static unsigned char test_app[0x1000],test_other[0x1000],test_home[0x600];
static unsigned char *current_unit;
static unsigned power_calls;
static unsigned char *test_get_proc(void){return current_unit;}
static void test_set_power(void *unit,unsigned mode){
  assert(unit==test_app && mode==3);power_calls++;
}
#endif
int main(void){
#ifdef HMI_PROFILE_FIXED
  payload="setup_screen_registered 0x1000\n";
  assert(addr_load()==0);
  assert(!opens);
#ifdef HMI_PROFILE_006016
  assert(HMI_ADDR(setup_screen_registered,A_STC)==0x2f0064);
  assert(A_MAP_REDIRECTION==0x383275c);
#else
  assert(HMI_ADDR(setup_screen_registered,A_STC)==0x2f00ac);
#endif
  assert(PROFILE_CHECK==1 && W0_STC==0xe3710008);
  assert(!HMI_FEATURE_TOUCH && !HMI_FEATURE_TPM && !HMI_FEATURE_DEBUG);
  /* Exercise the actual guest comparator: every required site's four words,
     then independently corrupt each word and require rejection. */
#define CHECK_SITE(N) do { \
    profile_sig s={1,W0_##N,W1_##N,W2_##N,W3_##N,#N}; \
    unsigned words[4]={s.w0,s.w1,s.w2,s.w3}; \
    assert(sig_words_ok(&s,words)); \
    for(unsigned i=0;i<4;i++){words[i]^=1;assert(!sig_words_ok(&s,words));words[i]^=1;} \
    s.addr=0;assert(!sig_ok(&s)); \
  } while(0)
  CHECK_SITE(STC); CHECK_SITE(PMD); CHECK_SITE(PM); CHECK_SITE(POWER_SET);
  CHECK_SITE(CTRL_EVENT); CHECK_SITE(CCS_BUTTON); CHECK_SITE(MAPSURF);
  CHECK_SITE(UNMAP); CHECK_SITE(MAP_NOTIFY);
#undef CHECK_SITE
#ifdef HMI_PROFILE_006016
  get_proc=test_get_proc;power_set=test_set_power;app_pu=test_app;home_app=test_home;
  current_unit=test_other;
  for(unsigned i=0;i<2000;i++)auto_power_on();
  assert(!power_calls);
  current_unit=test_app;
  for(unsigned i=0;i<AUTO_POWER_TICKS;i++)auto_power_on();
  assert(!power_calls);auto_power_on();assert(power_calls==1);
  assert(test_home[HOME_POWER_FLAG]==1 && test_home[HOME_AUX_FLAG]==0);
  for(unsigned i=0;i<20;i++)auto_power_on();assert(power_calls==1);
#endif
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
            for profile in ("default", "1803", "006016"):
                with self.subTest(profile=profile):
                    command = ["clang", "-w", "-D_FORTIFY_SOURCE=0", "-ffunction-sections",
                               "-fdata-sections", linker_flag, "-I", str(source_dir)]
                    if profile == "1803":
                        command.append("-DHMI_PROFILE_1803=1")
                    elif profile == "006016":
                        command.append("-DHMI_PROFILE_006016=1")
                    result = subprocess.run(command + [str(source), "-o", str(executable)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
