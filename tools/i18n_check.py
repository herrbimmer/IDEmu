#!/usr/bin/env python3
"""Checks that user-facing text in the GUI and in the Python message sources is covered by idemu/web/i18n.js.

Scans string literals in idemu/web/*.js, messages in the Python sources (raise, ApiError, step, error and note values, progress
calls) and the text tables/data files that reach the UI. Anything that looks Portuguese (diacritics or common words), plus UI-looking
English in the JS and in the English text tables, must be a dictionary entry or match a rule. Lists what is missing and exits 1.

Usage: python3 tools/i18n_check.py
"""
import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'idemu', 'web')
I18N_JS = os.path.join(WEB, 'i18n.js')
JS_FILES = ['util.js', 'wizard.js', 'tabs.js', 'cluster.js', 'run.js', 'coding.js', 'app.js', 'stats.js', 'envtools.js', 'packages.js', 'onboarding.js']
PY_FILES = ['server', 'catalog', 'runtime', 'builder', 'gps', 'sshbridge', 'canbus', 'coding', 'codegen', 'swfl', 'ifs', 'guestfs', 'most', 'v850', 'sshshell', 'stats', 'vin', 'sysfiles', 'mgu7', 'mgu', 'cic', 'phone', 'coding7', 'coding8']

DIACRITICS = re.compile(r'[áàâãéêíóôõúüçÁÀÂÃÉÊÍÓÔÕÚÜÇ]')
PT_WORDS = re.compile(r'(?<![\w.\-/#_])(?:' + '|'.join("""
    para do da dos das em um uma com sem por ao aos na nos nas no pelo pela ou que se mas ainda deve
    arquivo arquivos pasta pastas ambiente ambientes rota rotas sinal sinais quadro quadros tempo dados chassi marca papel
    iniciar parar compilar gravar excluir duplicar escolher selecionar mostrar voltar confirmar cancelar copiar limpar fechar
    novo nova carro tela rede porta portas modo erro falha nenhum nenhuma inativo ativo pronto completo linhas pontos raio
    desconhecido desconhecida ausente indisponível iniciando compilando aguardando carregando parado ligado desligado
    """.split()) + r')(?![\w\-_])', re.I)
# Literals that look like UI English in the JS but are key names, headers or error names.
UI_EN = re.compile(r'^(?:[A-Z][a-z]+(?:[ ,.:\'?!-]|$)|\d+ [a-z]+ )')

# Not user-facing, or deliberately untranslated: routes (hash URLs), keyboard keys, HTTP, native language names, product names.
ALLOW = {
    'ambientes', '#/ambientes', 'novo', 'pt_BR', 'Português (Brasil)', 'Português (Portugal)', 'Español', 'Français', 'Türkçe',
    'Escape', 'Enter', 'Tab', 'Shift', 'Alt', 'Ctrl', 'Control', 'Content-Type', 'x', 'Rolls-Royce', 'Navigation Business', 'Navigation Professional', 'EntryNav', '#nav a[data-route="ambientes"]',
}


def _read_strings(text):
    """Every JS string literal (single or double quoted) in text, decoded."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in '\'"':
            j, buf = i + 1, []
            while text[j] != c:
                if text[j] == '\\':
                    j += 1
                    buf.append({'n': '\n', 't': '\t'}.get(text[j], text[j]))
                else:
                    buf.append(text[j])
                j += 1
            out.append(''.join(buf))
            i = j + 1
        elif text.startswith('/*', i):
            i = text.index('*/', i) + 2
        else:
            i += 1
    return out


def _table(src, name):
    m = re.search(r'/\* I18N-%s-BEGIN \*/(.*?)/\* I18N-%s-END \*/' % (name, name), src, re.S)
    if not m:
        raise SystemExit('i18n.js: markers I18N-%s-BEGIN/END not found' % name)
    pairs = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith('['):
            parts = _read_strings(line)
            if len(parts) != 2:
                raise SystemExit('i18n.js: expected one [pt, en] pair per line: %s' % line[:100])
            pairs.append((parts[0], parts[1]))
    return pairs


def load_tables():
    """(DICT pairs, RULES pairs) parsed from i18n.js, in file order."""
    with open(I18N_JS, encoding='utf-8') as f:
        src = f.read()
    return _table(src, 'DICT'), _table(src, 'RULES')


def js_literals(src):
    """(line, text) of each string and template literal in JS source, skipping comments and regex literals."""
    out, i, n, line, prev = [], 0, len(src), 1, ''
    while i < n:
        c = src[i]
        if c == '\n':
            line += 1
            i += 1
        elif c.isspace():
            i += 1
        elif src.startswith('//', i):
            i = src.find('\n', i)
            i = n if i < 0 else i
        elif src.startswith('/*', i):
            j = src.index('*/', i) + 2
            line += src.count('\n', i, j)
            i = j
        elif c in '\'"`':
            j, buf, start = i + 1, [], line
            while src[j] != c:
                if src[j] == '\\':
                    j += 1
                    buf.append({'n': '\n', 't': '\t'}.get(src[j], src[j]))
                else:
                    if src[j] == '\n':
                        line += 1
                    buf.append(src[j])
                j += 1
            out.append((start, ''.join(buf)))
            i = j + 1
            prev = c
        elif c == '/' and (prev in ('', '(', ',', '=', ':', '[', '!', '&', '|', '?', '{', '}', ';', '+', '-', '*', '%', '<', '>', '~', '^') or re.search(r'\breturn$', src[max(0, i - 8):i].rstrip())):
            j, in_class = i + 1, False
            while src[j] != '/' or in_class:
                if src[j] == '\\':
                    j += 1
                elif src[j] == '[':
                    in_class = True
                elif src[j] == ']':
                    in_class = False
                j += 1
            i = j + 1
            prev = '/'
        else:
            prev = c
            i += 1
    return out


def norm_format(s):
    return re.sub(r'%[-+#0 ]*\d*(?:\.\d+)?[sdrxXfi]', '%s', s)


class Index:
    def __init__(self):
        self.pairs, self.rules = load_tables()
        self.pt = {p for p, _ in self.pairs}
        self.en = {e for _, e in self.pairs}
        self.rule_pt = {p.replace('%t', '%s') for p, _ in self.rules}
        self.res = [re.compile('^' + ''.join('(.+?)' if x == '%s' else re.escape(x) for x in re.split(r'(%s)', p)) + '$', re.S) for p in self.rule_pt]

    def known(self, s):
        c = s.strip()
        return c in self.pt or c in self.en or c in ALLOW

    def known_py(self, s):
        """A Python message: dictionary entry, or a rule, also when it is a fragment concatenated to a variable part."""
        if self.known(s):
            return True
        f = norm_format(s)
        if f in self.rule_pt or (f + '%s') in self.rule_pt or ('%s' + f) in self.rule_pt:
            return True
        if any(r.match(f) for r in self.res):
            return True
        return f.endswith(' ') and any(r.startswith(f) for r in self.rule_pt)


def looks_pt(s):
    return bool(DIACRITICS.search(s) or PT_WORDS.search(s))


def check_js(ix):
    problems = []
    for fn in JS_FILES:
        with open(os.path.join(WEB, fn), encoding='utf-8') as f:
            src = f.read()
        for line, s in js_literals(src):
            c = s.strip()
            if not re.search(r'[^\W\d_]', c) or c.startswith('<') or ix.known(c):
                continue
            if looks_pt(c) or UI_EN.match(c) or re.search(r'\{\w+\}', c):
                problems.append('%s:%d: %r' % (fn, line, s))
        # literals handed straight to the DOM skip h() and must go through IDE.t
        for m in re.finditer(r'(?:\.textContent|\.title|\.placeholder)\s*=\s*([^;]*);|\.fillText\(([^;]*)\);', src):
            stmt = m.group(1) or m.group(2) or ''
            if re.search(r'(?:IDE\.|\b)t\(', stmt):
                continue
            for _, s in js_literals(stmt):
                if looks_pt(s) and s.strip():
                    problems.append('%s:%d: not wrapped in IDE.t: %r' % (fn, src.count('\n', 0, m.start()) + 1, s))
    return problems


MSG_KEYS = {'step', 'error', 'note', 'message', 'boot_step'}
MSG_NAMES = {'note', 'st', 'step'}
MSG_ATTRS = {'step', 'err', 'error', 'last_error'}
MSG_CALLS = {'ApiError', 'progress', 'prog'}


def _strs(node):
    for c in ast.walk(node):
        if isinstance(c, ast.Constant) and isinstance(c.value, str):
            yield c


def _message_nodes(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Raise) and n.exc is not None:
            yield n.exc
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if (isinstance(t, ast.Attribute) and t.attr in MSG_ATTRS) or (isinstance(t, ast.Name) and t.id in MSG_NAMES) \
                        or (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant) and t.slice.value in MSG_KEYS):
                    yield n.value
        elif isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name) and n.target.id in MSG_NAMES:
            yield n.value
        elif isinstance(n, ast.Call):
            name = n.func.id if isinstance(n.func, ast.Name) else (n.func.attr if isinstance(n.func, ast.Attribute) else '')
            if name in MSG_CALLS:
                yield n
        elif isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value in MSG_KEYS:
                    yield v


def _module_table(tree, name):
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    raise SystemExit('table %s not found' % name)


def check_python(ix):
    problems = []
    trees = {}
    for mod in PY_FILES:
        with open(os.path.join(ROOT, 'idemu', mod + '.py'), encoding='utf-8') as f:
            trees[mod] = ast.parse(f.read())
        for node in _message_nodes(trees[mod]):
            for c in _strs(node):
                if looks_pt(c.value) and not ix.known_py(c.value):
                    problems.append('%s.py:%d: %r' % (mod, c.lineno, c.value))
    # catalog.py: every Portuguese constant outside the docstring is label text that reaches the wizard
    cat = trees['catalog']
    doc = ast.get_docstring(cat, clean=False)
    for c in _strs(cat):
        if c.value != doc and looks_pt(c.value) and not ix.known_py(c.value):
            problems.append('catalog.py:%d: %r' % (c.lineno, c.value))
    for _, (label, help_) in _module_table(cat, 'ROLE_TEXT').items():
        for s in (label, help_):
            if not ix.known(s):
                problems.append('catalog.py ROLE_TEXT: %r' % s)
    for table in ('COUNTRIES', 'DISPLAYS'):
        for _, s in _module_table(cat, table):
            if not ix.known(s) and s != 'China':
                problems.append('catalog.py %s: %r' % (table, s))
    # coding.py: English text tables
    cod = trees['coding']
    needed = []
    for _, group, label, desc in _module_table(cod, 'POPULAR'):
        needed += [group, label, desc]
    needed += _module_table(cod, 'VALUE_WORDS').values()
    needed += _module_table(cod, 'GROUP_LABELS').values()
    for s in needed:
        if s.strip() not in ix.en:
            problems.append('coding.py: no pt translation: %r' % s)
    # server.py: flash steps and backup notes (English)
    for n in ast.walk(trees['server']):
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'steps' for t in n.targets):
            for c in _strs(n.value):
                if c.value not in ix.en:
                    problems.append('server.py:%d: no pt translation: %r' % (c.lineno, c.value))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'backup':
            for c in _strs(n):
                if c.value[:1].isupper() and c.value not in ix.en:
                    problems.append('server.py:%d: no pt translation: %r' % (c.lineno, c.value))
    return problems


def check_data(ix):
    problems = []
    with open(os.path.join(ROOT, 'idemu', 'data', 'can_signals.json'), encoding='utf-8') as f:
        signals = json.load(f)['signals']
    for sg in signals:
        for key in ('label', 'group'):
            if sg.get(key) and not ix.known(sg[key]):
                problems.append('can_signals.json %s: %r' % (key, sg[key]))
        for v in (sg.get('enum') or {}).values():
            if looks_pt(v) and not ix.known(v):
                problems.append('can_signals.json enum: %r' % v)
    with open(os.path.join(ROOT, 'idemu', 'data', 'can_scenarios.json'), encoding='utf-8') as f:
        data = json.load(f)
    for sc in data if isinstance(data, list) else data.get('scenarios', []):
        for key in ('name', 'desc'):
            if sc.get(key) and not ix.known(sc[key]):
                problems.append('can_scenarios.json %s: %r' % (key, sc[key]))
    return problems


def check():
    ix = Index()
    return check_js(ix) + check_python(ix) + check_data(ix)


def main():
    problems = sorted(set(check()))
    if problems:
        print('i18n_check: %d string(s) missing from idemu/web/i18n.js:' % len(problems))
        for p in problems:
            print('  ' + p)
        return 1
    pairs, rules = load_tables()
    print('i18n_check: ok (%d dictionary entries, %d rules)' % (len(pairs), len(rules)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
