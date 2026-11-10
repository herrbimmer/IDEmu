"""Finds the addresses src/shim/hook.c needs inside HmiMain3D (a stripped ARM executable) at build time.

Nothing build-specific is stored: idemu/data/hmi_hooks.json describes each address by how to find it, not by its value:
  {"sym": "<dynamic symbol>", "add": n}         a symbol of the dynamic table (+ n)
  {"section": ".got"}                           start of a section
  {"code": [[word, mask], ...], "pick": i}      a function found by its first instructions: words compared under the mask (branch
                                                targets, pc-relative offsets and other immediates that move between builds are
                                                masked out); the match must be unique, or "pick" chooses among identical copies
  {"field": "<name>", "word": k, "mask": m}     a value read from the k-th instruction of another hook's function (struct offsets,
                                                prologue literals: "literal": true reads the pc-relative literal that instruction loads)
A hook whose description finds nothing (or more than one place) gets 0, which switches it off in the shim."""
import json, os, re, struct

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(HERE, 'data', 'hmi_hooks.json')


class Elf(object):
    def __init__(self, path):
        self.data = open(path, 'rb').read()
        d = self.data
        if d[:4] != b'\x7fELF' or d[4] != 1 or d[5] != 1: raise ValueError('not a 32-bit little-endian ELF')
        (self.entry, phoff, shoff, _flags, _eh, phes, phn, shes, shn, shstr) = struct.unpack_from('<IIIIHHHHHH', d, 0x18)
        self.segs = []
        for i in range(phn):
            t, off, va, _pa, fsz, msz, fl, _al = struct.unpack_from('<8I', d, phoff + i * phes)
            if t == 1: self.segs.append((va, off, fsz, fl))
        self.secs = {}
        if shoff and shn:
            raw = [struct.unpack_from('<10I', d, shoff + i * shes) for i in range(shn)]
            so = raw[shstr][4]
            for s in raw:
                n = d[so + s[0]:d.index(b'\0', so + s[0])].decode('latin-1')
                self.secs[n] = {'type': s[1], 'addr': s[3], 'off': s[4], 'size': s[5], 'link': s[6], 'entsize': s[9]}
        self._syms = None

    def off(self, va):
        for sva, off, fsz, _fl in self.segs:
            if sva <= va < sva + fsz: return off + va - sva
        return None

    def word(self, va):
        o = self.off(va)
        return struct.unpack_from('<I', self.data, o)[0] if o is not None else None

    def symbols(self):
        if self._syms is None:
            self._syms = {}
            ds, dstr = self.secs.get('.dynsym'), self.secs.get('.dynstr')
            if ds and dstr:
                for i in range(ds['size'] // 16):
                    nm, val, _sz, _info, _o, _sh = struct.unpack_from('<IIIBBH', self.data, ds['off'] + i * 16)
                    if not nm or not val: continue
                    p = dstr['off'] + nm
                    self._syms[self.data[p:self.data.index(b'\0', p)].decode('latin-1')] = val
        return self._syms

    def code_matches(self, words):
        """addresses (word aligned, in executable segments) where the masked words match"""
        rx = re.compile(_regex(words), re.DOTALL)
        out = []
        for sva, off, fsz, fl in self.segs:
            if not fl & 1: continue
            pos = off
            while True:
                m = rx.search(self.data, pos, off + fsz)
                if not m: break
                if (m.start() - off) % 4 == 0: out.append(sva + m.start() - off)
                pos = m.start() + 1
        return out


def _byte_rx(v, m):
    if m == 0xff: return re.escape(bytes([v]))
    if m == 0: return b'.'
    ok = [b for b in range(256) if b & m == v & m]
    return b'[' + b''.join(re.escape(bytes([b])) for b in ok) + b']'


def _regex(words):
    out = b''
    for v, m in words:
        for i in range(4): out += _byte_rx((v >> 8 * i) & 0xff, (m >> 8 * i) & 0xff)
    return out


def _literal(elf, va):
    """value loaded by "ldr rX, [pc, #+-imm]" at va"""
    w = elf.word(va)
    if w is None or (w & 0x0f7f0000) != 0x051f0000: return None
    return elf.word(va + 8 + ((w & 0xfff) if w & 0x00800000 else -(w & 0xfff)))


def load_hooks(path=HOOKS):
    d = json.load(open(path))
    return [(k, v) for k, v in d['hooks'].items()]


def scan(path, hooks=None, log=None):
    """{name: address} for every hook found (missing names are not found); log(name, why) for each one not found"""
    elf = Elf(path); hooks = load_hooks() if hooks is None else hooks
    found = {}
    for name, h in hooks:
        why = None
        if 'sym' in h:
            v = elf.symbols().get(h['sym'])
            if v is None: why = 'symbol missing'
            else: found[name] = v + h.get('add', 0)
        elif 'section' in h:
            s = elf.secs.get(h['section'])
            if not s: why = 'section missing'
            else: found[name] = s['addr']
        elif 'code' in h:
            ms = elf.code_matches([(int(v, 16), int(m, 16)) for v, m in h['code']])
            i = h.get('pick')
            if i is None and len(ms) == 1: found[name] = ms[0]
            elif i is not None and len(ms) == h.get('copies', len(ms)) and i < len(ms): found[name] = ms[i]
            else: why = '%d matches' % len(ms)
        elif 'field' in h:
            base = found.get(h['field'])
            if not base: why = 'needs ' + h['field']
            else:
                va = base + 4 * h['word']
                v = _literal(elf, va) if h.get('literal') else elf.word(va)
                if v is None: why = 'unreadable'
                else: found[name] = v & int(h.get('mask', '0xffffffff'), 16)
        if why and log: log(name, why)
    return found
