"""Run the guest address-table parser with host-side file mocks."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from idemu import builder


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
static const char extended[] = @V2_TABLE@;
static const unsigned expected_words[9][4] = @WORDS@;
static void rejected(const char *text){
  unsigned addresses[29],words[9][4];
  unsigned abi=profile_abi,power=home_power_flag,aux=home_aux_flag,home=main_home_offset;
  memcpy(addresses,&AD,sizeof AD); memcpy(words,profile_words,sizeof words);
  payload=text; overrides=invalids=0;
  assert(addr_load()==-1);
  assert(!memcmp(&AD,addresses,sizeof AD));
  assert(!memcmp(profile_words,words,sizeof words));
  assert(profile_abi==abi && home_power_flag==power && home_aux_flag==aux && main_home_offset==home);
  assert(!overrides && invalids==1);
}
static void changed_line(char *out,const char *table,const char *key,const char *value){
  char needle[128]; sprintf(needle,"%s ",key);
  const char *start=strstr(table,needle); assert(start && (start==table || start[-1]=='\n'));
  const char *after=strchr(start,'\n'); assert(after); after++;
  unsigned before=start-table; memcpy(out,table,before); out[before]=0;
  if(value)sprintf(out+before,"%s %s\n",key,value);
  strcat(out,after);
}
static unsigned char test_app[0x1000],test_other[0x1000],test_home[0x600];
static unsigned char *current_unit;
static unsigned power_calls;
static unsigned char *test_get_proc(void){return current_unit;}
static void test_set_power(void *unit,unsigned mode){
  assert(unit==test_app && mode==3);power_calls++;
}
/* The production installer below only substitutes the firmware-reading and
   patching boundaries. Its validation/order stays intact on a 64-bit host. */
static int bad_signature=-1,bad_export=-1;
static unsigned signature_checks,symbol_checks,patch_calls;
static int pre_sig_ok(const profile_sig *s){
  unsigned n=signature_checks++;assert(n<9);
  unsigned words[4];memcpy(words,expected_words[n],sizeof words);
  if((int)n==bad_signature)words[3]^=1;
  return sig_words_ok(s,words);
}
static void *pre_hk_sym(const char *lib,const char *symbol){
  unsigned n=symbol_checks++;return (int)n==bad_export?NULL:(void*)0x1000;
}
static int pre_hk_patch(void *target,void *fn){patch_calls++;return 0;}
static int pre_hk(const char *lib,const char *symbol,void *fn){patch_calls++;return 0;}
static void *pre_hk_tramp(u32 addr,void *fn){patch_calls++;return (void*)0x2000;}
static void *pre_sig_addr(const profile_sig *s){return (void*)(unsigned long)s->addr;}
static int pre_sig_patch(const profile_sig *s,void *fn){return pre_hk_patch(pre_sig_addr(s),fn);}
static void *pre_sig_tramp(const profile_sig *s,void *fn){return pre_hk_tramp(s->addr,fn);}
/* Callbacks are installed but never run by this stand-in. */
u32 map_cur[3];volatile int br_lock_v;
void br_init(void){}
u32 *br_begin(u32 op,u32 words){return NULL;}
u32 br_sync(u32 **reply){return 0;}
void br_flush(void){}
@INSTALL@
#endif
int main(int argc,char **argv){
#ifdef HMI_PROFILE_FIXED
  payload="setup_screen_registered 0x1000\n";
  assert(addr_load()==0);
  assert(!opens);
  assert(HMI_ADDR(setup_screen_registered,A_STC)==0x2f00ac);
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
#else
  if(argc==2){
    unsigned n;
    if(sscanf(argv[1],"sig%u",&n)==1){assert(n<9);bad_signature=n;}
    else if(sscanf(argv[1],"export%u",&n)==1){assert(n<10);bad_export=n;}
    else assert(!strcmp(argv[1],"good"));
    payload=extended;test_install_hooks();
    if(bad_signature>=0){
      assert(!patch_calls && signature_checks==(unsigned)bad_signature+1 && !symbol_checks);
    }else if(bad_export>=0){
      assert(!patch_calls && signature_checks==9 && symbol_checks==(unsigned)bad_export+1);
    }else assert(patch_calls>0 && signature_checks==9 && symbol_checks>=10);
    return 0;
  }
  unsigned defaults[29];
  memcpy(defaults,&AD,sizeof AD);
  assert(addr_load()==0);
  assert(opens==1 && !memcmp(&AD,defaults,sizeof AD) && !invalids);
  char table[4096],bad[8193],*p=table;
  for(unsigned i=0;i<29;i++)p+=sprintf(p,"%s 0x%x\n",AD_NAME[i],0x1000+i*4);
  payload=table; assert(addr_load()==0);
  assert(overrides==29);
  assert(profile_abi==0);
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
  /* The exact006 registry table changes addresses, layout and signature policy
     together; malformed replacements must retain this whole active state. */
  payload=extended; assert(addr_load()==0);
  assert(profile_abi==1 && home_power_flag==0x577 && home_aux_flag==0x576 && main_home_offset==0x958);
  assert(AD.setup_screen_registered==0x2f0064 && AD.map_redirection_obj==0x383275c);
  for(unsigned i=0;i<29;i++)assert(ad_runtime_required(i) ? ((unsigned*)&AD)[i]!=0 : ((unsigned*)&AD)[i]==0);
  assert(!memcmp(profile_words,expected_words,sizeof expected_words));
  for(unsigned hook=0;hook<9;hook++){
    profile_sig s={1,profile_words[hook][0],profile_words[hook][1],profile_words[hook][2],profile_words[hook][3],"test"};
    unsigned words[4];memcpy(words,profile_words[hook],sizeof words);
    assert(sig_words_ok(&s,words));
    for(unsigned i=0;i<4;i++){words[i]^=1;assert(!sig_words_ok(&s,words));words[i]^=1;}
    s.addr=0;assert(!sig_ok(&s));
  }
  const char *keys[]={"profile_abi","home_power_flag","home_aux_flag","main_home_offset"};
  for(unsigned i=0;i<4;i++){changed_line(bad,extended,keys[i],NULL);rejected(bad);}
  for(unsigned hook=0;hook<9;hook++)for(unsigned i=0;i<4;i++){
    char key[128];sprintf(key,"sig_%s_%u",PROFILE_SIG_NAME[hook],i);
    changed_line(bad,extended,key,NULL);rejected(bad);
    changed_line(bad,extended,key,"0x0");rejected(bad);
  }
  changed_line(bad,extended,"profile_abi","0x0");rejected(bad);
  changed_line(bad,extended,"profile_abi","0x2");rejected(bad);
  changed_line(bad,extended,"home_power_flag","0x0");rejected(bad);
  changed_line(bad,extended,"home_aux_flag","0x10000");rejected(bad);
  changed_line(bad,extended,"home_aux_flag","0x577");rejected(bad);
  changed_line(bad,extended,"main_home_offset","0x959");rejected(bad);
  changed_line(bad,extended,"setup_screen_registered","0x0");rejected(bad);
  changed_line(bad,extended,"setup_screen_registered","0x2f0065");rejected(bad);
  changed_line(bad,extended,"eds_display_enable","0x1000");rejected(bad);
  changed_line(bad,extended,"sig_setup_screen_registered_0","0x100000000");rejected(bad);
  strcpy(bad,extended);strcat(bad,"profile_abi 0x1\n");rejected(bad);
  strcpy(bad,extended);strcat(bad,"unknown_policy 0x1\n");rejected(bad);
  strcpy(bad,extended);bad[strlen(bad)-1]=0;rejected(bad);
  /* Wrong PU calls must not consume the app-thread startup counter. */
  get_proc=test_get_proc;power_set=test_set_power;app_pu=test_app;home_app=test_home;
  current_unit=test_other;
  for(unsigned i=0;i<2000;i++)auto_power_on();
  assert(!power_calls);profile_abi=0;
  for(unsigned i=0;i<2000;i++)auto_power_on();
  assert(!power_calls);profile_abi=1;
  assert(!power_calls);current_unit=test_app;
  for(unsigned i=0;i<AUTO_POWER_TICKS;i++)auto_power_on();
  assert(!power_calls);auto_power_on();assert(power_calls==1);
  assert(test_home[home_power_flag]==1 && test_home[home_aux_flag]==0);
  for(unsigned i=0;i<20;i++)auto_power_on();assert(power_calls==1);
  /* A later complete legacy table restores legacy policy, with no stale006 words. */
  payload=table;assert(addr_load()==0 && profile_abi==0);
  assert(home_power_flag==HOME_POWER_FLAG && home_aux_flag==HOME_AUX_FLAG && main_home_offset==MAIN_HOME_OFFSET);
  for(unsigned i=0;i<36;i++)assert(((unsigned*)profile_words)[i]==0);
  for(unsigned i=0;i<29;i++)assert(((unsigned*)&AD)[i]==0x1000+i*4);
  memset(bad,' ',8192); bad[8192]=0; rejected(bad);
  read_failure=1; rejected(table);
  read_failure=0; open_failure=13; rejected(NULL);
#endif
  return 0;
}
'''


@unittest.skipUnless(shutil.which("clang"), "clang is needed for the guest C parser self-check")
class AddressTableTest(unittest.TestCase):
    def test_arm_parser_does_not_call_unavailable_memory_clear_helpers(self):
        # Host C tests cannot expose ARM-only helpers emitted for aggregate zeroing.
        # The 006 libc lacks __aeabi_memclr8; explicit freestanding memset avoids it.
        source_dir = Path(__file__).resolve().parents[1] / "src" / "shim"
        with tempfile.TemporaryDirectory() as tmp:
            assembly = Path(tmp) / "hook.s"
            result = subprocess.run(
                ["clang", "-target", "armv7-none-eabi", "-march=armv7-a", "-mfloat-abi=soft",
                 "-ffreestanding", "-fPIC", "-Os", "-mno-unaligned-access", "-w", "-S",
                 str(source_dir / "hook.c"), "-o", str(assembly)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotRegex(assembly.read_text(), r"\b__aeabi_memclr\w*")

    def test_complete_tables_and_profile_isolation(self):
        source_dir = Path(__file__).resolve().parents[1] / "src" / "shim"
        linker_flag = "-Wl,-dead_strip" if sys.platform == "darwin" else "-Wl,--gc-sections"
        with tempfile.TemporaryDirectory() as tmp:
            source, executable = Path(tmp) / "check.c", Path(tmp) / "check"
            profile = json.loads((Path(builder.HERE) / "data/firmwares/nbtevo-006_016_002.json").read_text())
            words = "{" + ",".join("{" + ",".join(profile["runtime"]["signatures"][name]) + "}"
                                     for name in builder.MINIMAL_SIGNATURE_NAMES) + "}"
            table = builder.firmware_address_table(profile).decode()
            hook_source = (source_dir / "hook.c").read_text()
            installer = hook_source[hook_source.index("void install_hooks(void)"):]
            installer = installer.replace("void install_hooks(void)", "static void test_install_hooks(void)", 1)
            for name in ("sig_ok", "hk_sym", "hk_patch", "hk", "hk_tramp", "sig_addr", "sig_patch", "sig_tramp"):
                installer = re.sub(r"\b" + name + r"\(", "pre_" + name + "(", installer)
            installer = re.sub(r"\bhk_tdc_tramp\(", "pre_hk_tramp(", installer)
            source.write_text(HARNESS.replace("@V2_TABLE@", json.dumps(table)).replace("@WORDS@", words)
                              .replace("@INSTALL@", installer))
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
                    if profile == "default":
                        for case in ["good"] + ["sig%d" % i for i in range(9)] + ["export%d" % i for i in range(10)]:
                            with self.subTest(preflight=case):
                                subprocess.run([str(executable), case], check=True)


if __name__ == "__main__":
    unittest.main()
