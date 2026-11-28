"""Editor de codificação do iDrive 7 (MGU): parâmetros, valores atuais e de fábrica, backups.

Fonte: o próprio HMI (HmiMain3D). `tools/mgu/gen_coding7.py` extrai dele o dicionário de parâmetros (1500+), as 16 áreas da memória compartilhada
`rawcodingdata` e os valores de fábrica, e o `Mgu7.build` grava o resultado em mgu7/coding7.json.

"Gravar" (flash) = guarda as mudanças em env.json (coding.extra: {NOME: número}); ao subir a VM o IDEmu monta o bloco de bytes (fábrica + mudanças), manda
pela serial de entrada (linhas "c ...", ver src/mgu/wlstub.c) e o init do guest o escreve em /dev/shm/rawcodingdata antes de iniciar o HMI."""
import json, os, re
from . import coding as c6

AREA_LABELS = {'HMI_SPEECH': 'HMI and speech', 'CONNECTIVITY_A4A': 'Connectivity and phone apps', 'AUDIO_BROADCAST': 'Audio and broadcast', 'TELEMATICS': 'Telematics and services',
               'SYSTEM_CONFIGURATION': 'System configuration', 'APIX_CID_UND_ZIN': 'Screens and dimming', 'NAVIGATION': 'Navigation and maps', 'ENTERTAINMENT': 'Entertainment',
               'FES': 'Driving modes (FES)', 'EFFICIENT_DYNAMICS': 'EfficientDynamics', 'SARAH': 'Driver assistance (SARAH)', 'PARKEN': 'Parking and cameras',
               'TOUCH_COMMAND': 'Touch Command', 'KOMBI_HUD': 'Cluster and head-up display', 'LANGUAGE': 'Languages', 'M_GMBH': 'BMW M'}
STATUS_OFFSET, DATA_OFFSET = 0x28, 0x2c                 # no rawcodingdata: byte de estado e início das áreas
STATUS_REAL = 0x09                                      # bit 3 (bloco presente) + bit 0 (dados reais em +0x2c)
CAPTURE_SIZE = 4144
_cache = {}
# Com a codificação de fábrica do HMI (tudo desligado) o toque na tela central não faz nada: um ambiente novo já nasce com o toque codificado.
DEFAULT_HU = {'CID_TOUCH': 1, 'ZBE_TOUCH': 1, 'CID_TOUCH_SL': 1, 'CID_HMI_TOUCH': 1, 'CID_TOUCH_PROXIMITY': 1}


def path():
    from . import mgu7
    return os.path.join(mgu7.OUT, 'coding7.json')


def available():
    return os.path.isfile(path())


def load():
    p = path()
    if not os.path.isfile(p):
        raise ValueError('o dicionário de codificação do iDrive 7 ainda não foi extraído: reconstrua o ambiente')
    m = os.path.getmtime(p)
    if _cache.get('m') != m:
        with open(p) as f:
            d = json.load(f)
        areas = {a['id'] & 0xff: a for a in d['areas']}
        _cache.clear()                     # os campos ('fields', layout) vêm do arquivo anterior: posições e máscaras velhas gravariam nos bytes errados
        _cache.update(m=m, d=d, areas=areas)
    return _cache['d'], _cache['areas']


def layout(env):
    return 'rse' if env.get('role') == 'rse' else 'hu'


def fields(env):
    """{nome: dict(area, nome da área, posição absoluta no bloco, máscara, deslocamento, bits, opções)} dos parâmetros editáveis (1 byte, máscara não nula)."""
    d, areas = load()
    lay = layout(env)
    key = ('fields', lay)
    if key in _cache and _cache.get('m') == os.path.getmtime(path()):
        return _cache[key]
    out = _fields_for_layout(d, areas, lay)
    _cache[key] = out
    return out


def _fields_for_layout(d, areas, lay):
    out = {}
    for p in d['params']:
        a = areas.get(p['area'] & 0xff)
        if not a or p['end'] != p['start'] or not p['mask']:
            continue
        off, size = a[lay]
        if p['start'] >= size:
            continue
        m = p['mask']
        shift = (m & -m).bit_length() - 1
        out[p['name']] = {'name': p['name'], 'area': a['name'], 'pos': off + p['start'], 'mask': m, 'shift': shift, 'bits': bin(m).count('1'), 'vals': p['vals']}
    return out


def default_blob(env):
    d, _ = load()
    return bytearray(bytes.fromhex(d['blob'][layout(env)]))


def get_value(f, blob):
    return (blob[f['pos']] & f['mask']) >> f['shift']


def parse_hu_capture(value):
    """Read a complete rawcodingdata snapshot, not an E-Sys CAFD or NCD file."""
    message = 'Use uma captura rawcodingdata válida da tela central do iDrive 7 (4144 bytes).'
    if not isinstance(value, str) or len(value) != 2 * CAPTURE_SIZE:
        raise ValueError(message)
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(message) from exc
    if len(raw) != CAPTURE_SIZE or raw[STATUS_OFFSET] != STATUS_REAL:
        raise ValueError(message)
    return raw


def hu_capture_overrides(raw, schema):
    """Keep named HU fields only. Unknown bytes stay at the HMI's factory values."""
    areas = {a['id'] & 0xff: a for a in schema['areas']}
    editable = _fields_for_layout(schema, areas, 'hu')
    factory = bytes.fromhex(schema['blob']['hu'])
    if not editable or len(factory) > len(raw) - DATA_OFFSET or any(f['pos'] >= len(factory) for f in editable.values()):
        raise ValueError('O dicionário de codificação não corresponde ao layout da tela central.')
    payload = raw[DATA_OFFSET:DATA_OFFSET + len(factory)]
    overrides = {}
    for name, field in editable.items():
        value = get_value(field, payload)
        if value == get_value(field, factory):
            continue
        options = field['vals']
        if value >= 1 << field['bits'] or (options and not any(v == value or tag == 'VariantVal' for v, tag in options)):
            raise ValueError('A captura contém um valor incompatível com o firmware: %s.' % name)
        overrides[name] = value
    return overrides


def build_blob(env):
    """Bloco de codificação (fábrica + mudanças de env.coding.extra); None se não há mudança (o HMI usa a codificação padrão dele)."""
    coding = env.get('coding') or {}
    extra = coding.get('extra') or {}
    fs = fields(env)
    blob = default_blob(env)
    n = 0
    for name, v in extra.items():
        f = fs.get(name)
        if not f:
            if coding.get('hu_capture_imported'):
                raise ValueError('O dicionário não tem o parâmetro importado %s.' % name)
            continue
        blob[f['pos']] = (blob[f['pos']] & ~f['mask'] & 0xff) | ((int(v) << f['shift']) & f['mask'])
        n += 1
    return bytes(blob) if n else None


def serial_lines(blob):
    """Linhas "c DESLOCAMENTO HEX" (até 64 bytes cada) e a de fim, para a serial de entrada do guest (wlstub.c)."""
    out = ['c %x %s' % (i, blob[i:i + 64].hex()) for i in range(0, len(blob), 64)]
    out.append('c end')
    return out


def _label(name, short):
    return 'Active' if short == '' else c6.value_label(name, short)


def _options(f):
    out, seen = [], set()
    for v, s in f['vals']:
        if s == 'VariantVal' or v in seen or v >= (1 << f['bits']):
            continue
        seen.add(v)
        out.append({'value': v, 'raw': s or 'on', 'label': _label(f['name'], s)})
    return sorted(out, key=lambda o: o['value'])


def describe(env, env_dir):
    fs = fields(env)
    blob = default_blob(env)
    extra = (env.get('coding') or {}).get('extra') or {}
    popular = {p[0]: p for p in c6.POPULAR}
    out = []
    for name, f in fs.items():
        opts = _options(f)
        factory = get_value(f, blob)
        coded = name in extra
        p = popular.get(name)
        out.append({'name': name, 'label': p[2] if p else c6._humanize(name), 'desc': p[3] if p else '', 'popular': p[1] if p else None,
                    'group': f['area'], 'bits': f['bits'], 'max': (1 << f['bits']) - 1, 'options': opts, 'factory': factory,
                    'value': int(extra[name]) if coded else factory, 'coded': coded})
    groups = sorted({x['group'] for x in out})
    order = [p[0] for p in c6.POPULAR if p[0] in fs]
    return {'params': out, 'groups': [{'id': g, 'label': AREA_LABELS.get(g, g.replace('_', ' ').title())} for g in groups],
            'popular_order': order, 'popular_groups': list(dict.fromkeys(p[1] for p in c6.POPULAR if p[0] in fs)), 'backups': c6.list_backups(env_dir)}


def apply_changes(env, changes):
    """Aplica {NOME: valor} a env['coding']['extra']; None volta ao padrão. Devolve [(nome, antes, depois)]."""
    fs = fields(env)
    cd = env.setdefault('coding', {})
    extra = dict(cd.get('extra') or {})
    blob = default_blob(env)
    done = []
    for name, val in changes.items():
        f = fs.get(name)
        if not f:
            raise ValueError('parâmetro desconhecido: %s' % name)
        if val is None:
            done.append((name, extra.pop(name, None), None))
            continue
        num = val
        if not isinstance(num, int) or isinstance(num, bool):
            num = next((o['value'] for o in _options(f) if o['raw'] == str(val)), None)
        if num is None or not 0 <= num < (1 << f['bits']):
            raise ValueError('valor inválido para %s: %r' % (name, val))
        if num == get_value(f, blob):
            done.append((name, extra.pop(name, None), None))        # igual à fábrica: não precisa guardar
            continue
        done.append((name, extra.get(name), num))
        extra[name] = num
    cd['extra'] = extra
    return done
