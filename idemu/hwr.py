"""Handwriting on the iDrive Touch Controller (iDrive 5/6): what the touch controller does in address and search input.

In the car the controller recognises the character itself and sends the candidates to the HMI over MOST (FBlock 0xE5.01
CentralControlSystem, `CccsCharacterRecognition2` 0xC45 or `CccsCharacterRecognition` 0xC42, chosen by the controller's FktIDs). The HMI
switches recognition on in its spellers (`TP start mode 1 (C45)`) and tells the controller which characters it wants with
`CccsTouchControl` 0xC41 Set (byte 1: 1 digits, 2 upper case, 4 lower case, 8 special characters; byte 2: language).

Here the strokes drawn on the web UI's touch controller are collected; 0.7 s after the last one `bin/hwr` (tools/hwr, macOS Vision)
reads them, and the candidates go to the HMI as the controller would send them. Message (Status, read from HMI 006_017_006
`CTouchPadService::onCCSCharacterRecognitionStatus`): u8 number of candidates, then two candidates {u8 id, u8 probability %, u16
character (UTF-16)}, and for 0xC45 one more u8 (0). More than two candidates go in several messages (ids 0-1, 2-3, ...).
docs/TOUCH_CONTROLLER.md."""
import os, struct, subprocess, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HWR_BIN = os.path.join(ROOT, 'bin', 'hwr')
F_TOUCHCONTROL, F_CHARREC, F_CHARREC2 = 0xC41, 0xC42, 0xC45
PAUSE_S = 0.7                 # end of a character: no stroke for this long
LANGS = 'en-US,de-DE,fr-FR,it-IT,es-ES,pt-BR'

# Vision sometimes answers with a Cyrillic or Greek look-alike of a Latin letter
HOMOGLYPHS = dict(zip('АВЕКМНОРСТХУаеорсху' 'ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ', 'ABEKMHOPCTXYaeopcxy' 'ABEZHIKMNOPTYX'))
# characters a single handwritten glyph is easily read as
LOOKALIKES = {'0': 'O', 'O': '0', 'o': '0', '1': 'I', 'I': '1', 'l': '1', '5': 'S', 'S': '5', '2': 'Z', 'Z': '2', '8': 'B', 'B': '8',
              '6': 'G', 'G': '6', '9': 'g', 'q': '9', 'U': 'V', 'V': 'U'}


def candidates(found, classes=0x0F):
    """Vision's (character, confidence) list -> up to 4 (character, probability) for the HMI: look-alikes mapped to Latin, the other
    case and confusable characters added, filtered by the classes the HMI asked for (`CccsTouchControl` byte 1)."""
    out = []

    def add(c, p):
        if not c or c in (x for x, _ in out): return
        if c.isdigit(): ok = classes & 1
        elif c.isalpha(): ok = (classes & 2 and c.isupper()) or (classes & 4 and c.islower()) or (not c.isupper() and not c.islower())
        else: ok = classes & 8
        if ok: out.append((c, max(1, min(100, int(p)))))
    for c, p in found:
        c = HOMOGLYPHS.get(c, c)
        add(c, p)
        if c.isalpha(): add(c.swapcase(), p - 10)
        if c in LOOKALIKES:
            add(LOOKALIKES[c], p - 20)
            if LOOKALIKES[c].isalpha(): add(LOOKALIKES[c].swapcase(), p - 30)
    return out[:4]


def messages(cands, fkt):
    """CccsCharacterRecognition(2) Status payloads for these candidates (two per message)."""
    n, out = len(cands), []
    for i in range(0, n, 2):
        pair = cands[i:i + 2] + [('\0', 0)] * (2 - len(cands[i:i + 2]))
        b = struct.pack('>B', n)
        for j, (c, p) in enumerate(pair):
            b += struct.pack('>BBH', (i + j) if c != '\0' else 0, p, ord(c) & 0xFFFF)
        if fkt == F_CHARREC2: b += b'\0'
        out.append(b)
    return out


def recognise(strokes, langs=LANGS):
    """strokes: [[(x, y), ...], ...] (0..1) -> [(character, confidence)] from bin/hwr; [] when it reads nothing."""
    if not os.path.isfile(HWR_BIN): raise FileNotFoundError('bin/hwr is missing: build it with tools/hwr/build.sh')
    txt = '\n'.join(' '.join('%.4f,%.4f' % p for p in s) for s in strokes if s) + '\n'
    r = subprocess.run([HWR_BIN, '--lang', langs], input=txt.encode(), capture_output=True, timeout=10)
    out = []
    for line in r.stdout.decode('utf-8', 'replace').splitlines():
        c, _, p = line.rpartition(' ')
        if c: out.append((c, int(p) if p.isdigit() else 50))
    return out


class Handwriting(object):
    """Collects the touch controller's strokes and, while the HMI has character recognition on, sends what they read as."""

    def __init__(self, bridge, log=lambda s: None):
        self.bridge, self.log = bridge, log
        self.strokes, self.cur, self.timer, self.lock = [], None, None, threading.Lock()
        self.last = None              # (candidates, time) of the last recognition, for the API

    def active(self):
        """Character recognition on: the HMI's last CccsTouchControl Set asks for some character class."""
        tc = getattr(self.bridge, 'ccs_touch_control', None)
        return bool(tc and len(tc) > 1 and tc[1] & 0x0F)

    def touch(self, x, y, state):
        """state 1 down, 2 move, 3 up (first finger only)."""
        with self.lock:
            if self.timer: self.timer.cancel(); self.timer = None
            if not self.active(): self.strokes, self.cur = [], None; return
            if state == 1 or self.cur is None: self.cur = []; self.strokes.append(self.cur)
            self.cur.append((x, y))
            if state == 3:
                self.cur = None
                self.timer = threading.Timer(PAUSE_S, self._done); self.timer.daemon = True; self.timer.start()

    def _done(self):
        with self.lock:
            strokes, self.strokes, self.timer = self.strokes, [], None
        if not strokes or not self.active(): return
        try:
            found = recognise(strokes)
        except Exception as e:
            self.log('handwriting: %s' % e); return
        tc = self.bridge.ccs_touch_control
        cands = candidates(found, tc[1] & 0x0F)
        self.last = (cands, time.time())
        if not cands:
            self.log('handwriting: nothing recognised (%d strokes)' % len(strokes)); return
        subs = self.bridge.subs.get((0xE5, 1), {})
        fkt = F_CHARREC2 if F_CHARREC2 in subs else F_CHARREC if F_CHARREC in subs else None
        if fkt is None:
            self.log('handwriting: the HMI has not subscribed to character recognition (no FktIDs answer?)'); return
        for b in messages(cands, fkt): self.bridge.publish(0xE5, fkt, b, 1)
        self.log('handwriting: %s' % ' '.join('%s %d%%' % c for c in cands))
