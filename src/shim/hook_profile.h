/* Firmware-specific HMI addresses and feature switches for hook.c. */
#ifdef HMI_PROFILE_1803
#define PROFILE_CHECK 1
#define HMI_FEATURE_TOUCH 0
#define HMI_FEATURE_MAP 1
#define HMI_FEATURE_TPM 0
#define HMI_FEATURE_LUA 0
#define HMI_FEATURE_DEBUG 0

#define A_STC 0x2f00ac
#define W0_STC 0xe3710008
#define W1_STC 0xe92d4830
#define W2_STC 0xe1a04000
#define W3_STC 0xe28db00c

#define A_PMD 0x17f75f0
#define W0_PMD 0xe92d4800
#define W1_PMD 0xe28db004
#define W2_PMD 0xe590003c
#define W3_PMD 0xe8bd8800

#define A_PM 0x17f7ce8
#define W0_PM 0xe92d4830
#define W1_PM 0xe3a01003
#define W2_PM 0xe28db00c
#define W3_PM 0xe1a04000

#define A_POWER_SET 0x213b54
#define W0_POWER_SET 0xe92d4830
#define W1_POWER_SET 0xe1a05000
#define W2_POWER_SET 0xe28db00c
#define W3_POWER_SET 0xe24dd008

#define A_CTRL_EVENT 0x2479a4
#define W0_CTRL_EVENT 0xe59f3058
#define W1_CTRL_EVENT 0xe3a00040
#define W2_CTRL_EVENT 0xe92d4830
#define W3_CTRL_EVENT 0xe28db00c

#define A_CCS_BUTTON 0x2d6bac
#define W0_CCS_BUTTON 0xe92d4df0
#define W1_CCS_BUTTON 0xe1a0a003
#define W2_CCS_BUTTON 0xe59f30bc
#define W3_CCS_BUTTON 0xe28db01c

#define A_MAPSURF 0x27d8764
#define W0_MAPSURF 0xe92d4ff0
#define W1_MAPSURF 0xe59f45f8
#define W2_MAPSURF 0xe28db020
#define W3_MAPSURF 0xe59f35f4

#define A_UNMAP 0x27d7d40
#define W0_UNMAP 0xe92d49f0
#define W1_UNMAP 0xe59f426c
#define W2_UNMAP 0xe28db018
#define W3_UNMAP 0xe59f3268

#define A_MAP_NOTIFY 0x27d74d4
#define W0_MAP_NOTIFY 0xe92d4830
#define W1_MAP_NOTIFY 0xe1a04000
#define W2_MAP_NOTIFY 0xe5900040
#define W3_MAP_NOTIFY 0xe28db00c
#define A_MAP_REDIRECTION 0x38330b4

#define HOME_POWER_FLAG 0x577
#define HOME_AUX_FLAG 0x576
#define MAIN_HOME_OFFSET 0x958
#else
/* Validated NBTEvo_ID5_2403 profile. */
#define PROFILE_CHECK 0
#define HMI_FEATURE_TOUCH 1
#define HMI_FEATURE_MAP 1
#define HMI_FEATURE_TPM 1
#define HMI_FEATURE_LUA 1
#define HMI_FEATURE_DEBUG 1

#define A_STC 0x2f9308
#define A_PMD 0x18d8800
#define A_PM 0x18d8ef8
#define A_POWER_SET 0x2152c4
#define A_CTRL_EVENT 0x24a004
#define A_CCS_BUTTON 0x2dd6fc
#define A_MAPSURF 0x2a0d728
#define A_UNMAP 0x2a0cd04
#define A_MAP_NOTIFY 0x2a0c498
#define A_MAP_REDIRECTION 0x3af0a1c
#define HOME_POWER_FLAG 0x33b
#define HOME_AUX_FLAG 0x33a
#define MAIN_HOME_OFFSET 0x990

/* Signature checks are disabled for the already validated 24-03 profile. */
#define W0_STC 0
#define W1_STC 0
#define W2_STC 0
#define W3_STC 0
#define W0_PMD 0
#define W1_PMD 0
#define W2_PMD 0
#define W3_PMD 0
#define W0_PM 0
#define W1_PM 0
#define W2_PM 0
#define W3_PM 0
#define W0_POWER_SET 0
#define W1_POWER_SET 0
#define W2_POWER_SET 0
#define W3_POWER_SET 0
#define W0_CTRL_EVENT 0
#define W1_CTRL_EVENT 0
#define W2_CTRL_EVENT 0
#define W3_CTRL_EVENT 0
#define W0_CCS_BUTTON 0
#define W1_CCS_BUTTON 0
#define W2_CCS_BUTTON 0
#define W3_CCS_BUTTON 0
#define W0_MAPSURF 0
#define W1_MAPSURF 0
#define W2_MAPSURF 0
#define W3_MAPSURF 0
#define W0_UNMAP 0
#define W1_UNMAP 0
#define W2_UNMAP 0
#define W3_UNMAP 0
#define W0_MAP_NOTIFY 0
#define W1_MAP_NOTIFY 0
#define W2_MAP_NOTIFY 0
#define W3_MAP_NOTIFY 0
#endif
