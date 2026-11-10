"""Hook addresses of HmiMain3D: found at build time by idemu/hmiscan.py from idemu/data/hmi_hooks.json, in the order of the shim's enum."""
import json, os, re, struct, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from idemu import builder, hmiscan


def fake_elf(code, base=0x10000):
    """minimal ELF32 LE ARM executable: one executable PT_LOAD with code (list of u32) right after the headers"""
    hdr = 0x34 + 0x20
    eh = b'\x7fELF\x01\x01\x01' + bytes(9) + struct.pack('<HHIIIIIHHHHHH', 2, 40, 1, base + hdr, 0x34, 0, 0, 0x34, 0x20, 1, 0x28, 0, 0)
    body = struct.pack('<%dI' % len(code), *code)
    ph = struct.pack('<8I', 1, 0, base, base, hdr + len(body), hdr + len(body), 5, 0x1000)
    return eh + ph + body, base + hdr


class HmiHooksTest(unittest.TestCase):
    def test_names_match_shim_enum(self):
        src = open(os.path.join(ROOT, 'src', 'shim', 'hook.c')).read()
        body = re.search(r'enum \{ (HA_SETPOWER.*?), HA_N \};', src, re.S).group(1)
        self.assertEqual([n.strip()[3:] for n in body.split(',')], builder.HMI_ADDR_NAMES)

    def test_builtin_table_size_matches(self):
        src = open(os.path.join(ROOT, 'src', 'shim', 'hook.c')).read()
        body = re.search(r'static u32 ha\[HA_N\]=\{(.*?)\};', src, re.S).group(1)
        self.assertEqual(len([x for x in body.split(',') if x.strip()]), len(builder.HMI_ADDR_NAMES))

    def test_table_layout_and_missing_off(self):
        tab = builder.hmi_addr_table({'EDS': 0x1234})
        pairs = struct.unpack('<%dI' % (len(tab) // 4), tab)
        self.assertEqual(list(pairs[0::2]), list(range(len(builder.HMI_ADDR_NAMES))))
        i = builder.HMI_ADDR_NAMES.index('EDS')
        self.assertEqual(pairs[2 * i + 1], 0x1234)
        self.assertEqual(sum(1 for a in pairs[1::2] if a), 1)

    def test_overlay_table_has_only_found(self):
        tab = builder.hmi_addr_table({'SWT_INIT': 0x100, 'SWT_CP': 0x23}, full=False)
        idx = [builder.HMI_ADDR_NAMES.index('SWT_INIT'), builder.HMI_ADDR_NAMES.index('SWT_CP')]
        self.assertEqual(struct.unpack('<4I', tab), (idx[0], 0x100, idx[1], 0x23))
        self.assertNotEqual(len(tab), 8 * len(builder.HMI_ADDR_NAMES))         # the shim overlays a short table

    def test_hook_descriptions(self):
        hooks = hmiscan.load_hooks()
        names = [n for n, _ in hooks]
        self.assertFalse(set(names) - set(builder.HMI_ADDR_NAMES))
        for n, h in hooks:
            self.assertEqual(len(set(h) & {'sym', 'section', 'code', 'field'}), 1, n)
            if 'field' in h: self.assertLess(names.index(h['field']), names.index(n), n)     # its function is found first
            if 'code' in h: self.assertTrue(all(len(w) == 8 and len(m) == 8 for w, m in h['code']), n)

    def test_scan_code_field_and_literal(self):
        # f: push; ldr r3,[pc,#4]; strb r0,[r6,#0x23]; b <anywhere>; literal 0x7ec8
        f = [0xe92d4070, 0xe59f3004, 0xe5c60023, 0xea000123, 0x00007ec8]
        img, base = fake_elf([0xe1a00000] * 3 + f + [0xe1a00000] + f[:3] + [0xeaffffff, 0x00007ec8])
        with tempfile.NamedTemporaryFile(suffix='.elf', delete=False) as t: t.write(img)
        try:
            pat = [['e92d4070', 'ffffffff'], ['e59f3000', 'fffff000'], ['e5c60023', 'ffffffff'], ['ea000000', 'ff000000']]
            log = []
            got = hmiscan.scan(t.name, [('SWT_INIT', {'code': pat, 'pick': 1, 'copies': 2}),
                                        ('SWT_CP', {'field': 'SWT_INIT', 'word': 2, 'mask': '0xfff'}),
                                        ('TDC_K', {'field': 'SWT_INIT', 'word': 1, 'literal': True}),
                                        ('EDS', {'code': pat}),                     # two matches, no pick: not found
                                        ('OPNEW', {'sym': '_Znwj'})], log=lambda n, w: log.append(n))
            self.assertEqual(got, {'SWT_INIT': base + 4 * 9, 'SWT_CP': 0x23, 'TDC_K': 0x7ec8})
            self.assertEqual(sorted(log), ['EDS', 'OPNEW'])
        finally:
            os.unlink(t.name)


if __name__ == '__main__':
    unittest.main()
