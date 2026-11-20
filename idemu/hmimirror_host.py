"""Host side of the HMI mirror in "real_graphics" environments (docs/REAL_GRAPHICS.md).

The guest helper /fs/shim/realgfx/hmimirror (src/realgfx/hmimirror.c) owns a real QNX Screen window with id "256", the
HMI's surface on the car, and writes where its buffer lies in physical memory to /var/hmimirror.map. QEMU's guest RAM is
the shared file <run>/ram.bin (guest physical 0x80000000 = offset 0). This thread copies each new HMI frame from glhost's
frame file into that buffer as B,G,R,A and then bumps a counter in hmimirror's control page, so hmimirror posts the
window at once; LayerManagerService and Screen compose it, and the DSS model scans it out.
"""
import mmap, os, struct, time

RAM_BASE = 0x80000000
FRAME_MAGIC = 0x52464449        # 'IDFR'


def _read_map(shell_sock, stop_ev, log, wait_s=180):
    from . import guestfs
    end = time.time() + wait_s
    while not stop_ev.is_set():
        if time.time() > end:
            log('hmimirror: no /var/hmimirror.map after %d s; see /dev/shmem/realgfx.log and hmimirror.log in the guest' % wait_s)
            return None
        try:
            with guestfs.GuestSession(shell_sock, timeout=20) as g:
                rc, out = g.run('cat /var/hmimirror.map 2>/dev/null', 20)
            lines = [l.split() for l in out.decode('ascii', 'replace').splitlines() if l.strip()]
            if lines and lines[0][:2] == ['hmimirror', '1']:
                w, h, stride, nbytes = int(lines[0][2]), int(lines[0][3]), int(lines[0][4]), int(lines[0][5], 16)
                runs = [(int(a, 16), int(b, 16), int(c, 16)) for a, b, c in (l for l in lines[1:] if len(l) == 3)]
                ctl = [int(l[1], 16) for l in lines[1:] if len(l) == 2 and l[0] == 'ctl']
                if sum(r[2] for r in runs) >= nbytes and stride >= w * 4 and nbytes >= stride * h:
                    return w, h, stride, runs, (ctl[0] if ctl else None)
        except Exception as e:
            log('hmimirror: map not readable yet (%s)' % e)
        stop_ev.wait(3)
    return None


def run(run_dir, frame_path, stop_ev, log=lambda s: None):
    m = _read_map(os.path.join(run_dir, 'shell.sock'), stop_ev, log)
    if not m:
        return
    w, h, stride, runs, ctl = m
    log('hmimirror: window %dx%d stride %d, buffer at %s, control page %s' % (
        w, h, stride, ', '.join('%#x+%#x' % (p, n) for _, p, n in runs[:4]), '%#x' % ctl if ctl else 'none'))
    counter = 0
    ram = open(os.path.join(run_dir, 'ram.bin'), 'r+b')
    rm = mmap.mmap(ram.fileno(), 0)
    row = bytearray(w * 4); row[3::4] = b'\xff' * w
    out = bytearray(stride * h)
    if stride == w * 4: out[3::4] = b'\xff' * (w * h)
    fm, fkey, last, warned = None, None, None, False
    while not stop_ev.is_set():
        try:
            st = os.stat(frame_path)
            if fm is None or fkey != (st.st_ino, st.st_size):     # glhost may recreate the frame file
                with open(frame_path, 'rb') as ff: fm = mmap.mmap(ff.fileno(), 0, access=mmap.ACCESS_READ)
                fkey = (st.st_ino, st.st_size)
            magic, seq, fw, fh, busy = struct.unpack_from('<IIIII', fm, 0)
            if magic == FRAME_MAGIC and seq and (fw, fh) != (w, h) and not warned:
                log('hmimirror: HMI frame is %dx%d, the window %dx%d: not mirrored' % (fw, fh, w, h)); warned = True
            if magic == FRAME_MAGIC and seq and seq != last and not (busy and busy != seq) and (fw, fh) == (w, h) \
                    and len(fm) >= 32 + w * h * 3:
                rgb = fm[32:32 + w * h * 3]
                if stride == w * 4:
                    out[0::4] = rgb[2::3]; out[1::4] = rgb[1::3]; out[2::4] = rgb[0::3]
                else:
                    for y in range(h):
                        src = rgb[y * w * 3:(y + 1) * w * 3]
                        row[0::4] = src[2::3]; row[1::4] = src[1::3]; row[2::4] = src[0::3]
                        out[y * stride:y * stride + w * 4] = row
                for off, phys, length in runs:
                    a = phys - RAM_BASE
                    rm[a:a + length] = out[off:off + length]
                last = seq
                if ctl:                     # tells hmimirror to post the window now
                    counter = (counter + 1) & 0xffffffff
                    struct.pack_into('<I', rm, ctl - RAM_BASE, counter)
        except (ValueError, OSError, struct.error):
            fm = None
        stop_ev.wait(0.02)
    try:
        rm.close(); ram.close()
    except Exception:
        pass
