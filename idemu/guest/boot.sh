#!/bin/ksh
# IDEmu - init do guest (roda DENTRO da head unit virtual, a partir do disco de "shim").
# As imagens do sistema (sda/sdb) ficam intactas; tudo aqui é sobreposição em memória (symlinks do pathmgr).
R=/fs/sda0/repository/istep
# (o host já montou os discos e criou os atalhos /bin /lib /etc /opt /var -> $R/...)
export PATH=/boot/bin:/bin:/opt/sys/bin:/opt/car/bin:/opt/core/bin:.
export LD_LIBRARY_PATH=/opt/hmi/lib:/opt/hmi/otf:/boot/lib:/lib:/usr/lib:/opt/sys/lib:/opt/car/lib:.
# camada de tradução do hardware (GL/EGL/screen/ILM/OTF -> host)
ln -sP /fs/shim/lib/libscreen.so.1 /lib/libscreen.so.1
ln -sP /fs/shim/lib/libEGL.so.1 /lib/libEGL.so.1
ln -sP /fs/shim/lib/libGLESv2.so.1 /lib/libGLESv2.so.1
ln -sP /fs/shim/lib/libilmClient.gpp.so.1 /opt/sys/lib/libilmClient.gpp.so.1
ln -sP /fs/shim/lib/libBMWOTFapi.so.3 /opt/hmi/otf/libBMWOTFapi.so.3
ln -sP /fs/shim/lib/ioipc-idemu.so /lib/ioipc-idemu.so
# plugins de teste (idemu/plugins/): copiados para a RAM no começo do boot; o disco de shim é sobrescrito em execução
if [ -d /fs/shim/plug ]; then
  mkdir -p /dev/shmem/plug
  for d in /fs/shim/plug/*; do n=${d##*/}; mkdir -p /dev/shmem/plug/$n; cp $d/* /dev/shmem/plug/$n/; done
  ln -sP /dev/shmem/plug /opt/hmi/ID5/data/ro/Plugins
fi
export SYSNAME=nto TEMP=/dev/shmem HOME=/dev/shmem QNX_VERSION=qnx650 PROCESSOR=armle-v7 HOSTNAME=hu-omap BOOTMODE=TCFG MALLOC_MMAP_NOZERO=1
. /fs/shim/env.sh
mkdir -p /dev/shmem/idemu 2>/dev/null
pipe
# canal de shell para o SSH do host (UART2 = /dev/ser4, como no hardware original)
devc-sernuke -N -u4 -E -F -b921600 -c48000000/13 0x4806C000^2,105 > /dev/null 2>&1 &
# enlace do V850 virtual (UART4 = /dev/ser6): usado pelo transporte io-ipc (ioipc-idemu.so)
devc-sernuke -N -u6 -E -F -b921600 -c48000000/13 0x4806E000^2,102 > /dev/null 2>&1 &
waitfor /dev/ser4 10
( ksh -i < /dev/ser4 > /dev/ser4 2>&1 ) &
ksh /fs/shim/agent.sh > /dev/null 2>&1 &
waitfor /dev/ser6 10
echo IDEMU_STAGE services
ksh /fs/shim/rc.sh > /var/rc.log 2>&1
# real_graphics environments (docs/REAL_GRAPHICS.md): the firmware's own QNX Screen and LayerManagerService
[ -f /fs/shim/realgfx/start.sh ] && { echo IDEMU_STAGE realgfx; ksh /fs/shim/realgfx/start.sh; }
echo IDEMU_STAGE hmi
[ "$HMI_DELAY" -gt 0 ] && sleep $HMI_DELAY
cd /opt/hmi
# IDEMU_HMI_ON (runtime, com 2 núcleos): "on -R 1" prende o HMI e suas threads no CPU0, como num núcleo só; os demais serviços usam o CPU1
# IDEMU_NO_HMI=1 (depuração): não inicia o HMI — os serviços ficam sozinhos, sem o laço de reinício que satura a CPU
if [ -z "$IDEMU_NO_HMI" ]; then
while : ; do $IDEMU_HMI_ON /opt/hmi/bin/HmiMain3D -c=DSI,MOSTSubSystem -ro=/opt/hmi/data/ro/ -rw=/var/opt/hmi/data/rw/ -sp=/var/opt/hmi/data/rw/ -vp=/opt/hmi/data/ro/ -cp=/opt/hmi/data/ro/ -iba1=/mnt/data/iba/swe1/ -iba2=/mnt/data/iba/anim-all/swe2/ -h=${IDEMU_HMI_HEARTBEAT:-10000} -z=4 -os=0 > /var/hmi.log 2>&1; s=$?; echo "HMI exit status $s at $(date)" >> /var/hmi.exit; echo "IDEMU_HMI_EXIT $s" ; sleep 3; done &
fi
echo IDEMU_STAGE up
