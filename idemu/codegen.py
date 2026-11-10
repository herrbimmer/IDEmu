"""Perfil de codificação do carro virtual -> tabela binária lida pelo shim do guest (/fs/shim/coding.tab).

A tabela de variáveis (nome -> bloco/byte/máscara/valor) vem do dicionário CODING_FEATURE extraído da libhmicoding
do próprio firmware (data/coding_dict.json.z)."""
import json, os, struct, zlib, collections

_DICT = None
def load_dict():
    global _DICT
    if _DICT is None:
        raw = open(os.path.join(os.path.dirname(__file__), 'data', 'coding_dict.json.z'), 'rb').read()
        v = json.loads(zlib.decompress(raw).decode())
        c = collections.OrderedDict()
        for x in v:
            c.setdefault(x['name'], []).append(x)
        _DICT = c
    return _DICT

def enum_values(name):
    c = load_dict()
    out = []
    for y in c.get(name, []):
        s = y['value'].replace('va_' + name + '_', '')
        if s != 'VariantVal' and s not in out:
            out.append(s)
    return out

LANG_FEATURE = {
    'de_DE': 'LANGUAGE_GERMAN', 'en_GB': 'LANGUAGE_ENGLISH_UK', 'en_US': 'LANGUAGE_ENGLISH_US',
    'es_ES': 'LANGUAGE_SPANISH', 'fr_FR': 'LANGUAGE_FRENCH', 'it_IT': 'LANGUAGE_ITALIAN',
    'pt_PT': 'LANGUAGE_PORTUGUESE', 'pt_BR': 'LANGUAGE_PORTUGUESE_BR', 'nl_NL': 'LANGUAGE_DUTCH',
    'pl_PL': 'LANGUAGE_POLISH', 'ru_RU': 'LANGUAGE_RUSSIAN', 'sv_SE': 'LANGUAGE_SWEDISH',
    'tr_TR': 'LANGUAGE_TURKISH', 'ja_JP': 'LANGUAGE_JAPANESE', 'ko_KR': 'LANGUAGE_KOREAN',
    'zh_CN': 'LANGUAGE_CHINESE_SIMPLIFIED', 'zh_TW': 'LANGUAGE_CHINESE_TRADITIONAL',
}
MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'okt', 'nov', 'dez']
NAVI_BY_COUNTRY = {'US': 'us', 'CA': 'us', 'CN': 'china', 'JP': 'japan', 'KR': 'korea', 'HK': 'hongkong', 'TW': 'taiwan'}

def navi_value(navi, country=None):
    """Valor de NAVI_VARIANTE. Versões antigas do assistente gravavam 'navi_professional'/'navi_business', que não existem no dicionário: viram a região do país."""
    if navi in ('navi_professional', 'navi_business', 'navi', True):
        return NAVI_BY_COUNTRY.get((country or '').upper(), 'ece')
    return navi or 'keine_navi'

def profile_for(env):
    """Converte env['coding'] + chassi/marca em {VARIAVEL: valor} do dicionário de codificação."""
    cd = env.get('coding', {})
    p = collections.OrderedDict()
    p['HMI_ID_VERSION'] = cd.get('hmi_version', 'id6_light')
    p['HMI_BRAND'] = env.get('brand', 'bmw')
    p['BAUREIHE'] = env.get('chassis', 'F30')
    p['PRODUKTLINIE'] = cd.get('product_line', 'lu_b')
    p['LCI'] = int(cd.get('lci', 1))
    p['A4A_PROD_YEAR'] = str(cd.get('year', 2017))
    p['A4A_PROD_MONTH'] = MONTHS[(int(cd.get('month', 7)) - 1) % 12]
    disp = cd.get('display', '10_25_1440x540')
    res = disp.split('_')[-1].replace('x', '_')
    p['CID_DISPLAY_RES'] = res
    p['CID_DISPLAY_SIZE'] = '_'.join(disp.split('_')[:2])
    p['CID_COLOR_DEPTH'] = '24'
    p['DISPLAY_VARIANTE'] = 'schmales_display' if disp.startswith('6_5') else 'breites_display'
    p['DISPLAY_SIZE_RESOLUTION'] = disp
    lang = cd.get('language', 'en_GB')
    for code, feat in LANG_FEATURE.items():
        p[feat] = 'master' if code == lang else 'list'
    p['NAVI_VARIANTE'] = navi_value(cd.get('navi', 'keine_navi'), cd.get('country'))
    p['EINHEITEN_MASTER'] = 1
    touch = 0 if cd.get('hu_variant') == 'entrynav' else 1          # EntryNav: só o controlador, sem tela de toque
    p.update({'ZBE_35UP': 0, 'ZBE_TOUCH': touch, 'ZBE_TOUCH_SPELLER': touch, 'ZBE_TOUCH_BROWSER': touch,
              'ZBE_TOUCH_INTERACTIVE_MAP': touch, 'CID_TOUCH': 0})
    for k, v in (cd.get('extra') or {}).items():
        p[k] = v
    return p

def has_touch_controller(env):
    """iDrive Touch Controller (touchpad on the controller) coded: ZBE_TOUCH of the profile (1 unless EntryNav or changed in the coding editor)."""
    v = profile_for(env).get('ZBE_TOUCH', 0)
    if isinstance(v, (bool, int)): return bool(v)
    for y in load_dict().get('ZBE_TOUCH', ()):
        if y['value'].replace('va_ZBE_TOUCH_', '') == str(v): return bool(y['val'])
    return False

def build_table(profile):
    """Retorna (bytes_da_tabela, linhas_aplicadas, avisos)."""
    c = load_dict()
    rows = []; warn = []
    for k, val in profile.items():
        if k not in c:
            warn.append('variável desconhecida: %s' % k); continue
        e = c[k][0]; num = None
        if isinstance(val, int):
            num = val
        else:
            for y in c[k]:
                s = y['value'].replace('va_' + k + '_', '')
                if s == val or s == str(val):
                    num = y['val']
        if num is None:
            warn.append('valor inválido para %s: %r (opções: %s)' % (k, val, ', '.join(enum_values(k)[:12])))
            continue
        shift = (e['mask'] & -e['mask']).bit_length() - 1
        rows.append(struct.pack('<HHBB', e['blk'], e['byte'] + e['e'], e['mask'], (num << shift) & e['mask']))
    return b''.join(rows), len(rows), warn
