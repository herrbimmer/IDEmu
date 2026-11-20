#!/bin/ksh
# "real_graphics" environments (docs/REAL_GRAPHICS.md): the firmware's own QNX Screen server and LayerManagerService,
# beside IDEmu's HMI path. boot.sh runs this after the services and before the HMI; QEMU then has the OMAP5430 DSS model.
# IDEmu's shims replace /lib/libscreen.so.1, libEGL and libGLESv2 by pathmgr links; the real files stay under $R/lib, so
# the processes of the real stack put $R/lib first in LD_LIBRARY_PATH.
# Logs in the guest: /dev/shmem/realgfx.log, /dev/shmem/lms.log, /dev/shmem/hmimirror.log; sloginfo has the [LMGR] lines.
L=/dev/shmem/realgfx.log
R=/fs/sda0/repository/istep
G=$R/lib/graphics/omap5430_ES2_0
. /fs/shim/realgfx/mode.sh                      # RG_W, RG_H: the environment's display (written by the builder)
echo "realgfx: preparing ${RG_W}x${RG_H}" > $L
cp /fs/shim/realgfx/graphics.conf /dev/shmem/graphics.conf || echo "realgfx: graphics.conf copy failed" >> $L
cp $R/lib/screen-sw.so /dev/shmem/screen-sw.so || echo "realgfx: screen-sw.so copy failed" >> $L
cp $R/lib/libswblit.so.1 /dev/shmem/libswblit.so || echo "realgfx: libswblit copy failed" >> $L
export GRAPHICS_ROOT=/dev/shmem
export LD_LIBRARY_PATH=/dev/shmem:$G:$R/lib:/opt/sys/lib:/opt/car/lib:/usr/lib
echo "realgfx: starting /bin/screen" >> $L
/bin/screen -c /dev/shmem/graphics.conf >> $L 2>&1
echo "realgfx: /bin/screen returned $?" >> $L
n=0
while [ ! -e /dev/screen ] && [ $n -lt 60 ]; do sleep 1; n=$((n + 1)); done
if [ ! -e /dev/screen ]; then echo "realgfx: no /dev/screen after 60 s" >> $L; exit 1; fi
echo "realgfx: /dev/screen after $n s" >> $L
export LD_LIBRARY_PATH=$R/lib:/dev/shmem:$G:/opt/sys/lib:/opt/hmi/lib:/opt/car/lib:/usr/lib
/opt/sys/bin/LayerManagerService > /dev/shmem/lms.log 2>&1 &
echo "realgfx: LayerManagerService started" >> $L
# The HMI's surface 256: a real Screen window with id "256" that the host fills with IDEmu's HMI frame (hmimirror).
# On the car the HMI itself creates that window and puts surface 256 on layer 0x80000000 through ILM; here the HMI talks
# to IDEmu's ILM shim, so the same scene is set with LayerManagerControl once the window is there.
(
n=0
while [ ! -e /dev/layermanager ] && [ $n -lt 30 ]; do sleep 1; n=$((n + 1)); done
HMIMIRROR_SCREEN_LIB=$R/lib/libscreen.so.1 /fs/shim/realgfx/hmimirror 256 $RG_W $RG_H > /dev/shmem/hmimirror.log 2>&1 &
n=0
while [ ! -e /var/hmimirror.map ] && [ $n -lt 30 ]; do sleep 1; n=$((n + 1)); done
sleep 2
C=/opt/sys/bin/LayerManagerControl
$C set screen 0 render order 0x80000000 >> $L 2>&1
$C set layer 0x80000000 render order 256 >> $L 2>&1
$C set layer 0x80000000 visibility 1 >> $L 2>&1
$C set surface 256 visibility 1 >> $L 2>&1
echo "realgfx: hmimirror window 256 and the scene set (map after $n s)" >> $L
) &
