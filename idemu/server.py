"""Servidor HTTP local do IDEmu (API em docs/API.md + arquivos estáticos da GUI web)."""
import os, re, subprocess, json, time, shutil, threading, traceback, mimetypes, datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import catalog, builder, runtime, codegen, coding, coding7, coding8, stats, mgu, mgu7, phone, cluster, carplay, cic, vin, sysfiles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENVS = os.path.join(ROOT, 'environments')
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')
VERSION = '0.1'

class ApiError(Exception):
    def __init__(self, msg, code=400): Exception.__init__(self, msg); self.code = code

def slug(s):
    s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
    return s or 'ambiente'

MIN_FREE = 1 << 30           # espaço livre mínimo (1 GiB) na pasta escolhida para a VM

def fs_space(path):
    """Espaço livre e permissões de uma pasta (GET /api/fs/space), usado ao escolher onde a VM fica."""
    p = os.path.abspath(os.path.expanduser(path or '~'))
    if not os.path.isdir(p): raise ApiError('pasta inexistente', 404)
    du = shutil.disk_usage(p)
    return {'path': p, 'free': du.free, 'total': du.total, 'writable': os.access(p, os.W_OK | os.X_OK), 'default': os.path.realpath(p) == os.path.realpath(ENVS)}

class App:
    def __init__(self):
        os.makedirs(ENVS, exist_ok=True)
        self.rt = None; self.builds = {}; self.flashes = {}; self.lock = threading.RLock()       # start/build/flash/delete: verificação e registro juntos (clique duplo não cria dois QEMU)

    # ---- ambientes ----
    def env_dir(self, eid):
        if not re.match(r'^[a-z0-9][a-z0-9\-]*$', eid or ''): raise ApiError('id inválido')
        return os.path.join(ENVS, eid)
    def env_kind(self, eid):
        try: return json.load(open(os.path.join(self.env_dir(eid), 'env.json'))).get('kind')
        except (OSError, ValueError): return None
    def load_env(self, eid):
        p = os.path.join(self.env_dir(eid), 'env.json')
        if not os.path.isfile(p): raise ApiError('ambiente não encontrado', 404)
        env = json.load(open(p))
        env['build'] = self.build_info(eid)
        env['fast_boot'] = env.get('fast_boot', True)
        env['snapshot'] = self.snapshot_info(eid, env)
        return env
    def snapshot_info(self, eid, env):
        if env['build']['state'] != 'ready' or env.get('kind') in ('mgu22', 'cic'): return {'valid': False, 'size': 0, 'enabled': env['fast_boot'] and not env.get('kind')}
        e = dict(env); e.pop('build', None); e.pop('snapshot', None)
        try: return (mgu7.Mgu7Runtime if env.get('kind') == 'mgu7' else runtime.Runtime)(self.env_dir(eid), e).snapshot_info()
        except OSError: return {'valid': False, 'size': 0, 'enabled': env['fast_boot']}
    def save_env(self, env):
        e = dict(env); e.pop('build', None); e.pop('snapshot', None)
        os.makedirs(self.env_dir(e['id']), exist_ok=True)
        p = os.path.join(self.env_dir(e['id']), 'env.json'); tmp = p + '.tmp%d' % threading.get_ident()
        with open(tmp, 'w') as f: json.dump(e, f, indent=1, ensure_ascii=False)
        os.replace(tmp, p)          # atômico: quem lê ao mesmo tempo (a lista de ambientes) nunca vê o arquivo pela metade
    def build_info(self, eid):
        b = self.builds.get(eid)
        if b: return {k: b[k] for k in ('state', 'pct', 'step', 'error', 'built_at')}
        d = self.env_dir(eid)
        if self.env_kind(eid) == 'mgu7':
            if mgu7.image_ready(): return {'state': 'ready', 'pct': 100, 'step': 'Pronto', 'error': None, 'built_at': datetime.datetime.fromtimestamp(os.path.getmtime(mgu7.OUT + '/root.img')).isoformat(timespec='seconds')}
            return {'state': 'none', 'pct': 0, 'step': '', 'error': None, 'built_at': None}
        if self.env_kind(eid) == 'cic':
            if cic.image_ready(): return {'state': 'ready', 'pct': 100, 'step': 'Pronto', 'error': None, 'built_at': datetime.datetime.fromtimestamp(os.path.getmtime(cic.OUT + '/build.json')).isoformat(timespec='seconds')}
            return {'state': 'none', 'pct': 0, 'step': '', 'error': None, 'built_at': None}
        if self.env_kind(eid) == 'mgu22':
            if mgu.image_ready(): return {'state': 'ready', 'pct': 100, 'step': 'Pronto', 'error': None, 'built_at': datetime.datetime.fromtimestamp(os.path.getmtime(mgu.OUT + '/base.cpio')).isoformat(timespec='seconds')}
            return {'state': 'none', 'pct': 0, 'step': '', 'error': None, 'built_at': None}
        bj = os.path.join(d, 'build.json')
        if os.path.isfile(bj) and all(os.path.isfile(os.path.join(d, 'images', n)) for n in ('boot.ifs', 'sda.img', 'sdb.img', 'shim.img')):
            return {'state': 'ready', 'pct': 100, 'step': 'Pronto', 'error': None,
                    'built_at': datetime.datetime.fromtimestamp(os.path.getmtime(bj)).isoformat(timespec='seconds')}
        return {'state': 'none', 'pct': 0, 'step': '', 'error': None, 'built_at': None}
    def _alloc_home(self, eid, home):
        """Guarda a VM numa pasta escolhida: cria <home>/<id> e liga environments/<id> a ela por um link simbólico, então o resto do IDEmu segue usando
        environments/<id>. Devolve o caminho real escolhido, ou None para a pasta padrão."""
        if not home: return None
        sp = fs_space(home)
        if sp['default']: return None
        if not sp['writable']: raise ApiError('sem permissão para gravar na pasta escolhida')
        if sp['free'] < MIN_FREE: raise ApiError('a pasta escolhida tem menos de 1 GB livre')
        real = os.path.realpath(sp['path']); target = os.path.join(real, eid)
        if os.path.lexists(self.env_dir(eid)): raise ApiError('já existe um ambiente com esse id')
        if os.path.exists(target) and os.listdir(target): raise ApiError('já existe uma pasta "%s" com arquivos dentro da pasta escolhida' % eid)
        os.makedirs(target, exist_ok=True)
        os.symlink(target, self.env_dir(eid))
        return real
    def _free_id(self, base, home=None):
        eid = base; i = 2
        while os.path.lexists(self.env_dir(eid)) or (home and os.path.exists(os.path.join(os.path.realpath(os.path.expanduser(home)), eid))):
            eid = '%s-%d' % (base, i); i += 1
        return eid
    def list_envs(self):
        out = []
        for n in sorted(os.listdir(ENVS)):
            if os.path.isfile(os.path.join(ENVS, n, 'env.json')):
                try: out.append(self.load_env(n))
                except Exception: pass
        return out
    def create(self, d):
        name = (d.get('name') or '').strip() or 'Novo ambiente'
        eid = self._free_id(slug(name), d.get('home'))
        dvin = ((d.get('coding') or {}).get('vin') or '').upper()
        if dvin and not vin.VIN_RE.match(dvin): raise ApiError('VIN deve ter 17 caracteres (sem I, O, Q)')
        if d.get('kind') == 'mgu7':
            if not catalog.packages_ok('mgu7'): raise ApiError('faltam arquivos do iDrive 7: escolha-os (ou a pasta) na etapa de arquivos')
            role = d.get('role') or 'hu'
            if role not in ('hu', 'rse'): raise ApiError('tela do iDrive 7 desconhecida (use hu ou rse)')
            rse = role == 'rse'
            env = {'id': eid, 'name': name, 'created': datetime.datetime.now().isoformat(timespec='seconds'), 'kind': 'mgu7', 'role': role, 'series': 'RSE' if rse else 'HU', 'chassis': 'RSE' if rse else 'HU', 'brand': 'bmw',
                   'model_name': d.get('model_name') or ('BMW RSE (banco traseiro)' if rse else 'BMW iDrive 7 (tela central)'), 'swfl': {},
                   'coding': {'language': 'en_GB', 'units': 'metric', 'country': 'GB', 'vin': dvin, 'display': '1920x1080' if rse else '1920x720', 'hmi_version': 'id7', 'navi': '',
                              'extra': {} if rse else dict(coding7.DEFAULT_HU)}, 'net': {}}
            return self._save_new(env, d.get('home'))
        if d.get('kind') == 'cic':
            if not catalog.packages_ok('cic'): raise ApiError('o CIC precisa dos pacotes swfl_000003a6 e swfl_00000417 (versão 008_090_002)')
            env = {'id': eid, 'name': name, 'created': datetime.datetime.now().isoformat(timespec='seconds'), 'kind': 'cic', 'series': 'E90', 'chassis': 'CIC', 'brand': 'bmw',
                   'model_name': d.get('model_name') or 'BMW CIC High', 'swfl': {}, 'coding': {'language': 'de_DE', 'units': 'metric', 'country': 'DE', 'vin': dvin, 'display': '1280x480', 'hmi_version': 'id4', 'navi': ''}, 'net': {}}
            return self._save_new(env, d.get('home'))
        if d.get('kind') == 'mgu22':
            if not catalog.packages_ok('mgu22'): raise ApiError('faltam arquivos do iDrive 8: escolha-os (ou a pasta) na etapa de arquivos')
            env = {'id': eid, 'name': name, 'created': datetime.datetime.now().isoformat(timespec='seconds'), 'kind': 'mgu22', 'series': 'G70', 'chassis': 'G70', 'brand': 'bmw',
                   'model_name': d.get('model_name') or 'BMW i7', 'swfl': {}, 'coding': {'language': 'en_GB', 'units': 'metric', 'country': 'GB', 'vin': dvin, 'display': '14_9_2880x960', 'hmi_version': 'id8', 'navi': ''}, 'net': {}}
            return self._save_new(env, d.get('home'))
        sw = d.get('swfl') or {}
        for r in ('os', 'brand', 'hmi'):
            if not sw.get(r) or not os.path.isfile(sw[r]): raise ApiError('arquivo SWFL ausente ou inexistente para "%s"' % r)
        cd = dict({'language': 'en_GB', 'units': 'metric', 'country': 'GB', 'vin': '', 'year': 2017, 'month': 7, 'lci': 1,
                   'display': '10_25_1440x540', 'hmi_version': 'id6_light', 'navi': 'ece', 'hu_variant': 'professional'}, **(d.get('coding') or {}))
        if not catalog.hu_variant(cd.get('hu_variant')): raise ApiError('tipo de head unit desconhecido: %s' % cd.get('hu_variant'))
        cd['navi'] = codegen.navi_value(cd.get('navi'), cd.get('country'))
        if cd.get('vin') and not re.match(r'^[A-HJ-NPR-Z0-9]{17}$', cd['vin'].upper()): raise ApiError('VIN deve ter 17 caracteres (sem I, O, Q)')
        net = dict({'ssh_port': 2222, 'can_port': 29536, 'gps_port': 29537}, **(d.get('net') or {}))
        env = {'id': eid, 'name': name, 'created': datetime.datetime.now().isoformat(timespec='seconds'),
               'series': d.get('series', ''), 'chassis': d.get('chassis', 'F30'), 'brand': d.get('brand', 'bmw'),
               'model_name': d.get('model_name', ''), 'swfl': {k: sw[k] for k in ('os', 'brand', 'hmi')}, 'coding': cd, 'net': net}
        if codegen.enum_values('BAUREIHE') and env['chassis'] not in codegen.enum_values('BAUREIHE'): raise ApiError('chassi desconhecido: ' + env['chassis'])
        return self._save_new(env, d.get('home'))
    def _save_new(self, env, home):
        real = self._alloc_home(env['id'], home)
        if real: env['home'] = real
        try: self.save_env(env)
        except Exception:
            self.delete(env['id']); raise
        return self.load_env(env['id'])
    def update(self, eid, d):
        env = self.load_env(eid); env.pop('build', None); env.pop('snapshot', None)
        if d.get('name'): env['name'] = d['name']
        if 'fast_boot' in d: env['fast_boot'] = bool(d['fast_boot'])
        if 'coding' in d:
            if not isinstance(d['coding'], dict): raise ApiError('coding deve ser um objeto')
            env['coding'].update(d['coding'])
            v = (env['coding'].get('vin') or '').upper(); env['coding']['vin'] = v
            if v and not vin.VIN_RE.match(v): raise ApiError('VIN deve ter 17 caracteres (sem I, O, Q)')
        if 'net' in d: env['net'].update(d['net'])
        for k in ('chassis', 'series', 'model_name'):
            if d.get(k) is not None: env[k] = d[k]
        if not env.get('kind'):
            if env['coding'].get('hu_variant') and not catalog.hu_variant(env['coding']['hu_variant']): raise ApiError('tipo de head unit desconhecido')
            if codegen.enum_values('BAUREIHE') and env['chassis'] not in codegen.enum_values('BAUREIHE'): raise ApiError('chassi desconhecido: ' + env['chassis'])
        # recodificar: refaz só o shim (rápido) se o ambiente já foi compilado (só o iDrive 5/6 tem shim; os outros aplicam a codificação na próxima partida).
        # Antes de salvar: se falhar, o env.json continua descrevendo o shim que está no disco.
        if not env.get('kind') and self.build_info(eid)['state'] == 'ready' and ('coding' in d or 'chassis' in d):
            try: self._rebuild_shim(eid, env)
            except Exception as e:
                raise ApiError('falha ao regravar a codificação: %s' % e, 500)
        self.save_env(env)
        return self.load_env(eid)
    def _extract_cfg(self, env, os_dir):
        """Extrai do SWFL do sistema só o que o shim precisa (starter.cfg, io-ipc-o5.cfg, persistTracemost.bin) para <os_dir>."""
        from . import swfl
        tmp = os_dir + '_x'
        base = 'fs/sda0/repository/istep/'
        want = {(base + 'opt/sys/etc', 'starter.cfg'), (base + 'etc', 'io-ipc-o5.cfg'), (base + 'opt/sys/etc', 'persistTracemost.bin')}
        swfl.extract(env['swfl']['os'], tmp, lambda tp, n, m: (tp.rstrip('/'), n) in want)
        for d, n in want:
            src = os.path.join(tmp, d, n)
            if os.path.exists(src):
                target = os.path.join(os_dir, d[len(base):]); os.makedirs(target, exist_ok=True)
                shutil.copy(src, target)
        shutil.rmtree(tmp, ignore_errors=True)
    def start_build(self, eid):
        with self.lock: return self._start_build(eid)
    def _start_build(self, eid):
        env = self.load_env(eid); env.pop('build', None); env.pop('snapshot', None)
        if self.rt and self.rt.id == eid and self.rt.state != 'stopped': raise ApiError('pare o ambiente antes de compilar')
        b = self.builds.get(eid)
        if b and b['state'] == 'building': raise ApiError('já compilando')
        if (self.flashes.get(eid) or {}).get('state') == 'running': raise ApiError('aguarde a gravação da codificação terminar')
        k = env.get('kind')
        if k:                                          # CIC, iDrive 7 e 8: a imagem é compartilhada entre os ambientes da geração
            if (k == 'mgu22' and mgu.image_ready()) or (k == 'mgu7' and mgu7.image_ready()) or (k == 'cic' and cic.image_ready()):
                self.builds.pop(eid, None); return
            for oid, ob in self.builds.items():
                if oid != eid and ob.get('state') == 'building' and self.env_kind(oid) == k: raise ApiError('outro ambiente já está montando a imagem desta geração; aguarde')
        b = {'state': 'building', 'pct': 0, 'step': 'Iniciando', 'error': None, 'built_at': None, 'log': []}
        self.builds[eid] = b
        def log(s): b['log'].append(str(s)); b['log'] = b['log'][-300:]
        def prog(p, s): b['pct'] = p; b['step'] = s
        def run():
            try:
                if env.get('kind') == 'mgu7': mgu7.build(catalog.effective_psdz('mgu7'), log=log, progress=prog)
                elif env.get('kind') == 'mgu22': mgu.build(catalog.effective_psdz('mgu22'), log=log, progress=prog)
                elif env.get('kind') == 'cic': cic.build(catalog.effective_psdz('cic'), log=log, progress=prog)
                else: builder.build(env, self.env_dir(eid), log=log, progress=prog)
                b['state'] = 'ready'; b['pct'] = 100; b['step'] = 'Pronto'
                b['built_at'] = datetime.datetime.now().isoformat(timespec='seconds')
                time.sleep(0.5); self.builds.pop(eid, None)
            except Exception as e:
                log(traceback.format_exc()); b['state'] = 'error'; b['error'] = str(e)
        threading.Thread(target=run, daemon=True).start()
    def delete(self, eid):
        with self.lock: return self._delete(eid)
    def _delete(self, eid):
        if self.rt and self.rt.id == eid and self.rt.state in ('booting', 'running'): raise ApiError('pare o ambiente antes de excluir')
        if (self.builds.get(eid) or {}).get('state') == 'building': raise ApiError('aguarde o build terminar antes de excluir')
        if (self.flashes.get(eid) or {}).get('state') == 'running': raise ApiError('aguarde a gravação da codificação terminar')
        if any(j.get('state') == 'extracting' and os.path.abspath(k).startswith(os.path.abspath(self.env_dir(eid)) + os.sep) for k, j in list(sysfiles._jobs.items())):
            raise ApiError('aguarde a extração dos arquivos do sistema terminar')
        if self.rt and self.rt.id == eid: self.rt.stop(); self.rt = None
        self.builds.pop(eid, None); self.flashes.pop(eid, None); sysfiles.forget(eid)
        d = self.env_dir(eid)
        if os.path.islink(d):                          # VM numa pasta escolhida: apaga só a subpasta <home>/<id> que o IDEmu criou e depois o link
            real = os.path.realpath(d); os.unlink(d)
            if os.path.basename(real) == eid and os.path.isfile(os.path.join(real, 'env.json')): shutil.rmtree(real, ignore_errors=True)
            return
        shutil.rmtree(d, ignore_errors=True)
    def duplicate(self, eid, name):
        env = self.load_env(eid); env.pop('build', None); env.pop('snapshot', None)
        new = dict(env); new['name'] = name or env['name'] + ' (cópia)'
        home = new.pop('home', None)
        nid = self._free_id(slug(new['name']), home)
        new['id'] = nid; new['created'] = datetime.datetime.now().isoformat(timespec='seconds')
        try: real = self._alloc_home(nid, home)         # a cópia fica na mesma pasta da original, se ela ainda servir
        except ApiError: real = None
        if real: new['home'] = real
        self.save_env(new)
        for sub in ('images', 'build.json'):
            s = os.path.join(self.env_dir(eid), sub); t = os.path.join(self.env_dir(nid), sub)
            if os.path.isdir(s): shutil.copytree(s, t)
            elif os.path.isfile(s): shutil.copy(s, t)
        return self.load_env(nid)
    # ---- shim (iDrive 5/6) ----
    SHIM_INPUTS = (os.path.join('shim', 'lib'), os.path.join('guest', 'boot.sh'), os.path.join('guest', 'agent.sh'))
    def _rebuild_shim(self, eid, env):
        tmp = os.path.join(self.env_dir(eid), 'work'); os.makedirs(tmp, exist_ok=True)
        try:
            os_dir = os.path.join(tmp, 'os'); self._extract_cfg(env, os_dir)
            builder.build_shim(env, os_dir, os.path.join(self.env_dir(eid), 'images', 'shim.img'))
        finally: shutil.rmtree(tmp, ignore_errors=True)
    def _shim_stale(self, eid):
        """O shim.img do ambiente é mais velho que as bibliotecas do guest ou os scripts de boot (uma atualização do IDEmu): precisa ser refeito para valer."""
        try:
            p = os.path.join(self.env_dir(eid), 'images', 'shim.img'); built = os.path.getmtime(p)
            if os.path.getsize(p) > builder.SHIM_SECTORS * 512: return True      # shim de 32 MB (antes da mudança de endereço): refaz no tamanho novo
        except OSError: return False
        here = os.path.dirname(os.path.abspath(__file__))
        for rel in self.SHIM_INPUTS:
            p = os.path.join(here, rel)
            for f in ([os.path.join(p, n) for n in os.listdir(p)] if os.path.isdir(p) else [p]):
                try:
                    if os.path.getmtime(f) > built: return True
                except OSError: pass
        return False
    # ---- execução ----
    def start(self, eid, cold=False, _flash=False):
        with self.lock: return self._start(eid, cold, _flash)
    def _start(self, eid, cold=False, _flash=False):
        if self.rt and self.rt.state in ('booting', 'running'): raise ApiError('já existe um ambiente em execução; pare-o primeiro')
        env = self.load_env(eid); env.pop('build', None); env.pop('snapshot', None)
        if self.build_info(eid)['state'] != 'ready': raise ApiError('compile o ambiente antes de iniciar')
        if not _flash and (self.flashes.get(eid) or {}).get('state') == 'running': raise ApiError('aguarde a gravação da codificação terminar')   # a própria gravação reinicia a head unit (_flash)
        if self.rt and self.rt.state != 'stopped':          # o anterior parou com erro: encerra o que tiver sobrado dele (QEMU, renderizador, portas CAN/GPS)
            try: self.rt.stop()
            except Exception: traceback.print_exc()
        k = env.get('kind')
        if not k and self._shim_stale(eid):              # IDEmu atualizado: refaz o shim (correções do guest, como a entrada do rotor) antes de subir
            try: self._rebuild_shim(eid, env); print('shim de %s refeito (bibliotecas do guest mais novas)' % eid)
            except Exception as e: print('aviso: shim de %s não foi refeito (%s); usando o anterior' % (eid, e))
        self.rt = cic.CicRuntime(self.env_dir(eid), env) if k == 'cic' else mgu.MguRuntime(self.env_dir(eid), env) if k == 'mgu22' else mgu7.Mgu7Runtime(self.env_dir(eid), env) if k == 'mgu7' else runtime.Runtime(self.env_dir(eid), env)
        self.last_id = eid
        try: self.rt.start(cold=cold)
        except Exception as e: raise ApiError(str(e), 500)
    # ---- codificação (coding) ----
    def coding_info(self, eid):
        env = self.load_env(eid)
        if env.get('kind') == 'cic': raise ApiError('a edição de codificação ainda não existe para o CIC')
        try: d = coding7.describe(env, self.env_dir(eid)) if env.get('kind') == 'mgu7' else coding8.describe(env, self.env_dir(eid)) if env.get('kind') == 'mgu22' else coding.describe(env, self.env_dir(eid))
        except Exception as e: raise ApiError('não foi possível ler os parâmetros de codificação: %s' % e, 500)
        d['running'] = bool(self.rt and self.rt.id == eid and self.rt.state in ('booting', 'running'))
        d['flash'] = self.flash_status(eid)
        return d
    def flash_status(self, eid):
        j = self.flashes.get(eid)
        return dict(j) if j else {'state': 'idle'}
    def flash(self, eid, changes=None, note='', reset=False, restore=None):
        with self.lock: return self._flash(eid, changes, note, reset, restore)
    def _flash(self, eid, changes=None, note='', reset=False, restore=None):
        """Grava a codificação: backup -> aplica -> regenera shim.img -> reinicia a head unit (se estiver ligada) -> confere que o HMI leu a tabela nova."""
        env = self.load_env(eid); env.pop('build', None); env.pop('snapshot', None)
        if env.get('kind') == 'cic': raise ApiError('a gravação de codificação ainda não existe para o CIC')
        if env.get('kind') in ('mgu7', 'mgu22'): return self.flash7(eid, env, changes, note, reset, restore)
        if self.build_info(eid)['state'] != 'ready': raise ApiError('compile o ambiente antes de gravar a codificação')
        if (self.flashes.get(eid) or {}).get('state') == 'running': raise ApiError('já existe uma gravação em andamento')
        if self.rt and self.rt.state in ('booting', 'running') and self.rt.id != eid: raise ApiError('outro ambiente está em execução; pare-o primeiro')
        before = json.loads(json.dumps(env.get('coding') or {}))
        try:
            if restore: env['coding'] = coding.read_backup(self.env_dir(eid), restore)['coding']; done = []
            else:
                if reset: env['coding']['extra'] = {}
                done = coding.apply_changes(env, changes or {})
            tab, rows, warn = codegen.build_table(codegen.profile_for(env))
        except (ValueError, OSError) as e: raise ApiError(str(e))
        was_running = bool(self.rt and self.rt.id == eid and self.rt.state in ('booting', 'running'))
        steps = ['Backing up the current coding', 'Writing the coding', 'Restarting the head unit', 'Checking the head unit read it'] if was_running else ['Backing up the current coding', 'Writing the coding']
        j = {'state': 'running', 'step': 0, 'steps': steps, 'error': None, 'rows': rows, 'warnings': warn, 'changes': len(done), 'restarted': was_running, 'verified': False, 'backup': None, 't0': time.time()}
        self.flashes[eid] = j
        def run():
            try:
                old = dict(env); old['coding'] = before
                j['backup'] = coding.backup(old, self.env_dir(eid), note or 'Before flash')
                j['step'] = 1
                tmp = os.path.join(self.env_dir(eid), 'work'); os.makedirs(tmp, exist_ok=True)
                os_dir = os.path.join(tmp, 'os'); self._extract_cfg(env, os_dir)
                if was_running: self.stop()
                self.save_env(env)
                shutil.rmtree(os.path.join(self.env_dir(eid), 'snapshot'), ignore_errors=True)    # o snapshot embute a codificação antiga
                builder.build_shim(env, os_dir, os.path.join(self.env_dir(eid), 'images', 'shim.img'))
                shutil.rmtree(tmp, ignore_errors=True)
                if was_running:
                    j['step'] = 2
                    self.start(eid, _flash=True)
                    rt = self.rt; end = time.time() + 300
                    while rt.state == 'booting' and time.time() < end: time.sleep(0.2)
                    if rt.state != 'running': raise RuntimeError(rt.err or 'a head unit não voltou depois da gravação')
                    j['step'] = 3
                    log = os.path.join(rt.logd, 'renderer.log'); end = time.time() + 20; found = None
                    while time.time() < end and found is None:
                        with open(log, errors='replace') as f:
                            m = re.search(r'coding: profile from /fs/shim/coding\.tab, rows ([0-9a-f]+)', f.read())
                        if m: found = int(m.group(1), 16)
                        else: time.sleep(0.25)
                    j['rows_read'] = found
                    if found != rows: raise RuntimeError('o HMI leu %s linhas de codificação em vez de %d' % (found, rows))
                    j['verified'] = True
                j['step'] = len(steps); j['state'] = 'done'
            except Exception as e:
                traceback.print_exc(); j['state'] = 'error'; j['error'] = str(e)
        threading.Thread(target=run, daemon=True).start()
        return dict(j)
    def flash7(self, eid, env, changes, note, reset, restore):
        """iDrive 7 e 8: grava as mudanças em env.json e reinicia a VM. O iDrive 7 manda o bloco de codificação pela serial e o guest o escreve na memória compartilhada antes do HMI;
        o iDrive 8 leva uma coding.tab própria no initramfs (coding8.py). Nos dois o guest imprime "== coding applied N" e a gravação confere N."""
        k8 = env.get('kind') == 'mgu22'; cmod = coding8 if k8 else coding7
        if self.build_info(eid)['state'] != 'ready': raise ApiError('compile o ambiente antes de gravar a codificação')
        if (self.flashes.get(eid) or {}).get('state') == 'running': raise ApiError('já existe uma gravação em andamento')
        if self.rt and self.rt.state in ('booting', 'running') and self.rt.id != eid: raise ApiError('outro ambiente está em execução; pare-o primeiro')
        before = json.loads(json.dumps(env.get('coding') or {}))
        try:
            if restore: env['coding'] = coding.read_backup(self.env_dir(eid), restore)['coding']; done = []
            else:
                if reset: env['coding']['extra'] = dict(coding7.DEFAULT_HU) if not k8 and env.get('role', 'hu') == 'hu' else {}
                done = cmod.apply_changes(env, changes or {})
            blob = cmod.build_tab(env) if k8 else cmod.build_blob(env)
            want = len((blob or ''.join('x\n' for _ in coding8.factory_tab())).splitlines()) if k8 else (len(blob) if blob else 0)
        except (ValueError, OSError) as e: raise ApiError(str(e))
        was_running = bool(self.rt and self.rt.id == eid and self.rt.state in ('booting', 'running'))
        steps = ['Backing up the current coding', 'Writing the coding', 'Restarting the head unit', 'Checking the head unit read it'] if was_running else ['Backing up the current coding', 'Writing the coding']
        j = {'state': 'running', 'step': 0, 'steps': steps, 'error': None, 'rows': want, 'warnings': [], 'changes': len(done), 'restarted': was_running, 'verified': False, 'backup': None, 't0': time.time()}
        self.flashes[eid] = j
        def run():
            try:
                old = dict(env); old['coding'] = before
                j['backup'] = coding.backup(old, self.env_dir(eid), note or 'Before flash')
                j['step'] = 1
                if was_running: self.stop()
                self.save_env(env)
                shutil.rmtree(os.path.join(self.env_dir(eid), 'snapshot'), ignore_errors=True)       # o estado salvo embute a codificação antiga
                if was_running:
                    j['step'] = 2
                    self.start(eid, _flash=True)
                    rt = self.rt; end = time.time() + 400
                    while rt.state == 'booting' and time.time() < end: time.sleep(0.3)
                    if rt.state != 'running': raise RuntimeError(rt.err or 'a head unit não voltou depois da gravação')
                    j['step'] = 3
                    if blob or k8:
                        log = os.path.join(rt.logd, 'console.log'); end = time.time() + 20; found = None
                        while time.time() < end and found is None:
                            try:
                                with open(log, errors='replace') as f: m = re.search(r'== coding applied (\d+)', f.read())
                            except OSError: m = None
                            if m: found = int(m.group(1))
                            else: time.sleep(0.5)
                        j['rows_read'] = found
                        if found != want: raise RuntimeError('o guest gravou %s %s de codificação em vez de %d' % (found, 'linhas' if k8 else 'bytes', want))
                    j['verified'] = True
                j['step'] = len(steps); j['state'] = 'done'
            except Exception as e:
                traceback.print_exc(); j['state'] = 'error'; j['error'] = str(e)
        threading.Thread(target=run, daemon=True).start()
        return dict(j)
    def stop(self):
        if self.rt: self.rt.stop()
    def apply_vin(self, eid, v, variant=None):
        """Coloca o VIN no ambiente e ajusta o carro a ele (chassi, série, ano, HMI, mercado). A marca e a geração do iDrive não mudam num ambiente pronto."""
        env = self.load_env(eid)
        try: dec = vin.decode(v, wait=True)
        except ValueError as e: raise ApiError(str(e))
        sug = dec['env']; notes = list(dec.get('notes') or [])
        gen_env = {'cic': 'id4', 'mgu7': 'id7', 'mgu22': 'id8'}.get(env.get('kind')) or ('id5' if (env['coding'].get('hmi_version') or '').startswith('id5') else 'id6')
        upd = {'coding': {'vin': dec['vin']}}
        if not env.get('kind'):
            same_family = sug.get('generation') in ('id5', 'id6')
            if dec.get('found') and same_family:
                if catalog.BRAND_SWFL.get(sug['brand']) != catalog.BRAND_SWFL.get(env.get('brand')):
                    notes.append('O VIN é de um %s e o ambiente usa os arquivos da marca %s: o chassi não foi trocado (crie um ambiente novo para essa marca).' % (sug['brand'].upper(), (env.get('brand') or '').upper()))
                else:
                    upd.update(chassis=sug['chassis'], series=sug['series'] or env.get('series'), model_name=sug['model_name'])
                    c = dict(sug['coding']); c.pop('display', None)
                    if variant:
                        hv = catalog.hu_variant(variant)
                        if not hv: raise ApiError('tipo de head unit desconhecido')
                        c['hu_variant'] = variant; c['display'] = hv['display']
                    else: c.pop('hu_variant', None)
                    upd['coding'].update(c)
            elif sug.get('generation'): notes.append('Esse carro saiu de fábrica com o %s; este ambiente emula o %s. Só o VIN foi gravado.' % (sug['generation'].replace('id', 'iDrive '), gen_env.replace('id', 'iDrive ')))
        elif dec.get('found'):
            upd['model_name'] = ' '.join(x for x in [sug.get('chassis'), sug.get('model_name')] if x)
            if sug.get('generation') and sug['generation'] != gen_env: notes.append('Esse carro saiu de fábrica com o %s; este ambiente emula o %s.' % (sug['generation'].replace('id', 'iDrive '), gen_env.replace('id', 'iDrive ')))
        if self.rt and self.rt.id == eid and self.rt.state in ('booting', 'running'): notes.append('Reinicie o ambiente para o HMI ler a nova codificação.')
        return {'env': self.update(eid, upd), 'decode': dec, 'notes': notes}
    def need_rt(self):
        if not self.rt or self.rt.state in ('stopped',): raise ApiError('nenhum ambiente em execução', 409)
        return self.rt
    def need_can(self):
        rt = self.need_rt()
        if not rt.can: raise ApiError('barramento CAN ainda não disponível', 409)
        return rt.can
    def need_gps(self):
        rt = self.need_rt()
        if not rt.gps: raise ApiError('GPS ainda não disponível', 409)
        return rt.gps
    def phone_link(self):
        if getattr(self, '_phone', None) is None:
            self._phone = phone.PhoneLink(self)
        return self._phone

APP = App()
_STATS = None
def get_stats():
    global _STATS
    if _STATS is None: _STATS = stats.Sampler(APP, APP.env_dir)
    return _STATS

def native_pick(kind, prompt='', start=None):
    """Seletor nativo do macOS (osascript). Devolve o caminho escolhido, ou None se o usuário cancelar. Levanta ApiError se não houver como abrir o diálogo."""
    import subprocess
    q = lambda x: '"' + str(x).replace('\\', '\\\\').replace('"', '\\"') + '"'
    loc = ''
    if start and os.path.isdir(os.path.expanduser(start)): loc = ' default location (POSIX file %s)' % q(os.path.expanduser(start))
    verb = 'choose folder' if kind == 'folder' else 'choose file'
    if kind == 'files':
        script = ('tell application "System Events" to activate\nset L to (choose file with prompt %s%s with multiple selections allowed)\n'
                  'set o to ""\nrepeat with f in L\nset o to o & POSIX path of f & linefeed\nend repeat\no') % (q(prompt or ''), loc)
    else: script = 'tell application "System Events" to activate\nPOSIX path of (%s with prompt %s%s)' % (verb, q(prompt or ''), loc)
    try: r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=900)
    except FileNotFoundError: raise ApiError('seletor nativo indisponível neste sistema', 501)
    except subprocess.TimeoutExpired: return None
    if r.returncode != 0:
        if '-128' in r.stderr: return None            # cancelado
        raise ApiError('não foi possível abrir o seletor do macOS: %s' % r.stderr.strip()[:160], 501)
    return r.stdout.strip().rstrip('\n') or None

def fs_list(path):
    path = os.path.abspath(os.path.expanduser(path or '~'))
    if not os.path.isdir(path): raise ApiError('pasta inexistente', 404)
    ents = []
    try:
        for n in sorted(os.listdir(path), key=str.lower):
            if n.startswith('.'): continue
            p = os.path.join(path, n)
            try: d = os.path.isdir(p); sz = 0 if d else os.path.getsize(p)
            except OSError: continue
            ents.append({'name': n, 'dir': d, 'size': sz})
    except PermissionError: raise ApiError('sem permissão', 403)
    return {'path': path, 'parent': os.path.dirname(path) if path != '/' else None, 'entries': ents}

class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def _send(self, code, body, ctype='application/json', extra=None):
        if isinstance(body, (dict, list)): body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def _body(self):
        try: n = int(self.headers.get('Content-Length') or 0)
        except ValueError: raise ApiError('Content-Length inválido')
        if n < 0 or n > 64 << 20: raise ApiError('corpo do pedido inválido')
        if not n: return {}
        raw = self.rfile.read(n)
        try: d = json.loads(raw.decode() or '{}')
        except Exception: raise ApiError('JSON inválido')
        if not isinstance(d, dict): raise ApiError('o corpo deve ser um objeto JSON')
        return d
    def do_GET(self): self._route('GET')
    def do_POST(self): self._route('POST')
    def _foreign(self):
        """Pedido vindo de outro site (CSRF) ou por outro nome de host (DNS rebinding)? A API só atende a própria interface."""
        port = self.server.server_address[1]
        host = (self.headers.get('Host') or '').lower()
        loop = self.server.server_address[0] in ('127.0.0.1', 'localhost', '::1')
        if loop and host not in ('127.0.0.1:%d' % port, 'localhost:%d' % port, '[::1]:%d' % port): return True
        if (self.headers.get('Sec-Fetch-Site') or '') == 'cross-site': return True
        org = self.headers.get('Origin')
        if org and org != 'null' and urlparse(org).netloc.lower() != host: return True
        return False
    def _route(self, m):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path.startswith('/api/') and self._foreign(): raise ApiError('pedido de outra origem recusado', 403)
            if u.path.startswith('/api/'):
                r = self.api(m, u.path[5:].strip('/'), q)
                if isinstance(r, tuple): self._send(*r)
                else: self._send(200, r)
            else: self.static(u.path)
        except ApiError as e: self._send(e.code, {'error': str(e)})
        except (BrokenPipeError, ConnectionResetError): pass
        except (KeyError, ValueError, TypeError) as e:       # parâmetro ausente ou mal formado (since=abc, sem "code"...): erro do pedido, não do servidor
            self._send(400, {'error': 'parâmetro inválido: %s' % (e if not isinstance(e, KeyError) else 'falta %s' % e)}); traceback.print_exc()
        except Exception as e:
            self._send(500, {'error': '%s: %s' % (type(e).__name__, e)}); traceback.print_exc()
    def static(self, path):
        if path in ('', '/'): path = '/index.html'
        p = os.path.normpath(os.path.join(WEB, path.lstrip('/')))
        if not p.startswith(WEB + os.sep) or not os.path.isfile(p): raise ApiError('não encontrado', 404)
        ct = mimetypes.guess_type(p)[0] or 'application/octet-stream'
        self._send(200, open(p, 'rb').read(), ct + ('; charset=utf-8' if ct.startswith('text') or 'javascript' in ct else ''))
    def api(self, m, path, q):
        A = APP; P = path.split('/')
        if m == 'POST': d = self._body()
        else: d = {}
        if path == 'state':
            return {'settings': {'psdz_path': catalog.load_settings().get('psdz_path'), 'psdz_ok': catalog.psdz_ok(catalog.load_settings().get('psdz_path')), 'ui_language': catalog.load_settings().get('ui_language', 'en')}, 'envs': A.list_envs(),
                    'running': A.rt.id if A.rt and A.rt.state in ('booting', 'running') else None, 'version': VERSION}
        if path == 'settings' and m == 'POST' and 'ui_language' in d:
            if d['ui_language'] not in ('en', 'pt', 'es', 'fr', 'de', 'it', 'tr', 'ru', 'zh', 'ja'): raise ApiError('idioma inválido')
            catalog.save_settings({'ui_language': d['ui_language']}); return {'ok': True}
        if path == 'settings' and m == 'POST' and d.get('psdz_path') == '':
            catalog.save_settings({'psdz_path': None}); return {'ok': True, 'psdz_ok': False, 'message': 'pasta esquecida'}
        if path == 'settings' and m == 'POST':
            p = os.path.expanduser(d.get('psdz_path') or '')
            ok = catalog.psdz_ok(p)
            if ok: catalog.save_settings({'psdz_path': p})
            return {'ok': ok, 'psdz_ok': ok, 'message': 'PSDZData válido' if ok else 'pasta inválida: precisa conter swe/swfl e mainseries'}
        if path == 'catalog': return dict(catalog.build_catalog(catalog.load_settings().get('psdz_path')), envs_dir=ENVS)
        if path == 'fs/list': return fs_list(q.get('path'))
        if path == 'fs/space': return fs_space(q.get('path'))
        if path == 'pick' and m == 'POST':
            kind = d.get('kind') if d.get('kind') in ('folder', 'files') else 'file'
            r = native_pick(kind, d.get('prompt', ''), d.get('start'))
            if kind == 'files': return {'paths': [x for x in (r or '').split('\n') if x.strip()]}
            return {'path': r}
        if path == 'packages' and m == 'GET':
            if q.get('kind') not in ('cic', 'mgu7', 'mgu22'): raise ApiError('geração desconhecida')
            return catalog.package_status(q['kind'])
        if path == 'packages/pick' and m == 'POST':
            kind = d.get('kind')
            if kind not in ('cic', 'mgu7', 'mgu22'): raise ApiError('geração desconhecida')
            res = []
            for f in d.get('paths') or []:
                ok, msg = catalog.stage_file(f, kind); res.append({'path': f, 'ok': ok, 'message': msg})
            return dict(catalog.package_status(kind), results=res)
        if path == 'packages/scan' and m == 'POST':
            kind = d.get('kind')
            if kind not in ('cic', 'mgu7', 'mgu22'): raise ApiError('geração desconhecida')
            root = os.path.abspath(os.path.expanduser(d.get('path') or ''))
            if os.path.isfile(root): root = os.path.dirname(root)
            if not os.path.isdir(root): raise ApiError('pasta inexistente', 404)
            req = catalog.required_packages(kind)
            r = catalog.scan_folder(root, [x['id'] for x in req])
            want = {x['id']: x['version'] for x in req}; n = 0
            for sid, files in r['files'].items():
                for f in files:
                    if f['version'] == want.get(sid) and catalog.stage_file(f['path'], kind)[0]: n += 1; break
            return dict(catalog.package_status(kind), scanned_path=root, scanned=r['scanned'], timeout=r['timeout'], staged=n)
        if path == 'scan' and m == 'POST':
            root = os.path.abspath(os.path.expanduser(d.get('path') or ''))
            if os.path.isfile(root): root = os.path.dirname(root)
            if not os.path.isdir(root): raise ApiError('pasta inexistente', 404)
            ids = [i for i in (d.get('ids') or []) if re.match(r'^[0-9a-fA-F]{8}$', str(i))]
            if not ids: raise ApiError('nenhum arquivo para procurar')
            r = catalog.scan_folder(root, ids); r['path'] = root; return r
        if path == 'vin/decode':
            try: return vin.decode(q.get('vin') or d.get('vin'))
            except ValueError as e: raise ApiError(str(e))
        if path == 'stats': return get_stats().snapshot(q.get('env'), float(q.get('since', 0) or 0))
        if P[0] == 'env' and path == 'env/create' and m == 'POST': return A.create(d)
        if P[0] == 'env' and len(P) >= 2:
            eid = P[1]
            if len(P) == 2: return A.load_env(eid)
            act = P[2]
            if act in ('update', 'start', 'stop', 'delete', 'duplicate', 'snapshot', 'vin') and m != 'POST': raise ApiError('use POST', 405)
            if act == 'update': return A.update(eid, d)
            if act == 'vin': return A.apply_vin(eid, d.get('vin'), d.get('hu_variant'))
            if act == 'files':
                sub = P[3] if len(P) > 3 else ''
                env = A.load_env(eid)
                if not sub: return sysfiles.listdir(env, A.env_dir(eid), q.get('path', ''))
                if sub == 'status': return sysfiles.status(env, A.env_dir(eid))
                if sub == 'extract' and m == 'POST': return sysfiles.start_extract(env, A.env_dir(eid))
                if sub == 'remove' and m == 'POST': return sysfiles.remove(env, A.env_dir(eid))
                if sub == 'reveal' and m == 'POST': return sysfiles.reveal(env, A.env_dir(eid), d.get('path', ''))
                if sub == 'raw':
                    body, ctype, name = sysfiles.read(env, A.env_dir(eid), q.get('path', ''))
                    disp = 'inline' if q.get('inline') else 'attachment'
                    from urllib.parse import quote
                    return 200, body, ctype, {'Content-Disposition': "%s; filename*=UTF-8''%s" % (disp, quote(name))}
                raise ApiError('rota desconhecida', 404)
            if act == 'userfiles':
                env = A.load_env(eid)
                if env.get('kind') != 'cic': raise ApiError('arquivos do usuário só existem para o CIC', 400)
                dd = cic.userfiles_dir(A.env_dir(eid))
                if len(P) > 3 and P[3] == 'reveal':
                    if m != 'POST': raise ApiError('use POST', 405)
                    os.makedirs(dd, exist_ok=True)
                    r = subprocess.run(['open', dd], capture_output=True, text=True)
                    if r.returncode: raise ApiError('não consegui abrir a pasta: %s' % r.stderr.strip()[:160], 500)
                    return {'ok': True}
                fl = cic.userfiles_list(A.env_dir(eid))
                return {'dir': dd, 'mount': '/mnt/EFS_RO', 'files': fl, 'bytes': sum(f['size'] for f in fl)}
            if act == 'build' and m == 'POST': A.start_build(eid); return {'ok': True}
            if act == 'build':
                A.load_env(eid); b = A.builds.get(eid); i = A.build_info(eid)
                i['log'] = list(b['log'][-60:]) if b else []; return i
            if act == 'start': A.start(eid, cold=bool(d.get('cold'))); return {'ok': True}
            if act == 'snapshot' and len(P) > 3 and P[3] == 'delete':
                env = A.load_env(eid)
                if A.rt and A.rt.id == eid and A.rt.state == 'booting': raise ApiError('aguarde o boot terminar')
                shutil.rmtree(os.path.join(A.env_dir(eid), 'snapshot'), ignore_errors=True); return {'ok': True}
            if act == 'coding':
                sub = P[3] if len(P) > 3 else ''
                if not sub: return A.coding_info(eid)
                if sub == 'flash' and m == 'POST': return A.flash(eid, d.get('changes'), d.get('note', ''), bool(d.get('reset')), d.get('restore'))
                if sub == 'flash': A.load_env(eid); return A.flash_status(eid)
                if sub == 'backup' and m == 'POST':
                    env = A.load_env(eid); return {'ok': True, 'id': coding.backup(env, A.env_dir(eid), d.get('note', 'Manual backup')), 'backups': coding.list_backups(A.env_dir(eid))}
                raise ApiError('rota desconhecida', 404)
            if act == 'stop':
                if A.rt and A.rt.id == eid: A.stop()          # só para o ambiente pedido, não o que estiver rodando
                return {'ok': True}
            if act == 'delete': A.delete(eid); return {'ok': True}
            if act == 'duplicate': return A.duplicate(eid, d.get('name'))
        if path == 'v850/publish' and m == 'POST':       # depuração: envia o Status de uma propriedade MOST ao HMI
            rt = A.need_rt(); v = getattr(rt, 'v850', None)
            if not v: raise ApiError('V850 virtual indisponível', 409)
            n = v.bridge.publish(int(d['fblock']), int(d['fkt']), bytes.fromhex(d['data']), int(d.get('inst', 0)))
            return {'ok': True, 'delivered': n}
        if path == 'v850/devices' and m == 'POST':       # depuração: registra mais dispositivos MOST do HMI (lista de [fblock, inst])
            rt = A.need_rt(); v = getattr(rt, 'v850', None)
            if not v: raise ApiError('V850 virtual indisponível (ambiente parado ou modo externo)', 409)
            devs = [(int(a), int(b)) for a, b in d['devices']]
            v.bridge.register_devices(devs)
            return {'ok': True, 'registered': len(devs)}
        if path == 'cluster':                            # cluster (Kombi) e HUD virtuais: CAN + GPS + o que o HMI manda por MOST
            rt = A.need_rt()
            if getattr(rt, 'kind', None) or not getattr(rt, 'can', None): raise ApiError('o cluster e o HUD só existem no iDrive 5 e 6 em execução', 409)
            v = getattr(rt, 'v850', None)
            return cluster.snapshot(rt.can, getattr(rt, 'gps', None), v.bridge if v else None)
        if path == 'carplay':                            # CarPlay (iDrive 5/6): iPhone falso pelo MOST virtual (idemu/carplay.py)
            fl = A.flash_status(A.rt.id) if A.rt else {'state': 'idle'}
            if fl.get('state') == 'running':             # "Configurar CarPlay" reinicia a head unit: o progresso vem antes de exigir o ambiente rodando
                return {'state': 'off', 'step': '', 'error': None, 'name': carplay.NAME, 'show_keys': False, 'missing': [], 'flash': fl}
            rt = A.need_rt(); v = getattr(rt, 'v850', None)
            if getattr(rt, 'kind', None) or not v: raise ApiError('o CarPlay só existe no iDrive 5 e 6 em execução', 409)
            fake = getattr(rt, 'fake_iphone', None)
            if fake is None or fake.bridge is not v.bridge: fake = rt.fake_iphone = carplay.FakeIPhone(v.bridge, rt.ctl)
            missing = carplay.setup_missing(rt.env)
            if m == 'POST' and d.get('setup'):           # liga o CarPlay no ambiente: conn + variantes, CARPLAY_SWT pela gravação de codificação (reinicia a head unit)
                if not missing: raise ApiError('o CarPlay já está configurado neste ambiente')
                env = A.load_env(rt.id); A.save_env(carplay.setup_env(env))
                A.flash(rt.id, dict(carplay.CODING), 'Before CarPlay setup (CarPlay tab)')
                return dict(fake.status(), missing=missing, flash=A.flash_status(rt.id))
            if m == 'POST' and 'show_keys' in d: fake.show_keys(d['show_keys'])
            if m == 'POST' and d.get('fake_iphone') and missing:
                raise ApiError('o CarPlay não está configurado neste ambiente: use "Configurar CarPlay" primeiro', 409)
            if m == 'POST' and 'fake_iphone' in d: return dict(fake.set(bool(d['fake_iphone'])), missing=missing, flash=A.flash_status(rt.id))
            return dict(fake.status(), missing=missing, flash=A.flash_status(rt.id))
        if path == 'v850/seen':                          # depuração: últimas mensagens Set/Get do HMI por (FBlock, instância, função)
            rt = A.need_rt(); v = getattr(rt, 'v850', None)
            if not v: raise ApiError('V850 virtual indisponível', 409)
            fb = q.get('fblock'); now = time.time()
            return {'seen': [{'fblock': k[0], 'inst': k[1], 'fkt': k[2], 'op': e['op'], 'n': e['n'], 'age': round(now - e['t'], 1), 'data': e['data'].hex()}
                             for k, e in sorted(v.bridge.seen.items()) if fb is None or k[0] == int(fb, 0)]}
        if path == 'v850':
            rt = A.need_rt(); v = getattr(rt, 'v850', None)
            if not v: raise ApiError('V850 virtual indisponível (ambiente parado ou modo externo)', 409)
            return v.snapshot()
        if path == 'map':
            rt = A.need_rt(); mp = getattr(rt, 'map', None)
            if not mp: raise ApiError('mapa indisponível (ambiente parado)', 409)
            if m == 'POST':
                mp.set(zoom=d.get('zoom'), headup=d.get('headup'), night=d.get('night'), source=d.get('source'))
                catalog.save_settings({'map_source': mp.source, 'map_zoom': mp.zoom, 'map_headup': mp.headup, 'map_night': mp.night})
            return mp.state()
        if path == 'run/status':
            if not A.rt: return {'state': 'stopped', 'env': None, 'uptime_s': 0, 'boot_step': '', 'boot_pct': 0, 'ports': {}, 'frame_seq': 0, 'fps': 0, 'error': None}
            return A.rt.status()
        if path == 'run/frame':                          # próximo quadro, cru (RGB): a tela do navegador pede o seguinte assim que desenha este
            rt = A.need_rt(); since = int(q.get('since', -1)); end = time.time() + 1.5
            seq = rt.frame_seq()
            nap = 0.002
            while seq == since and time.time() < end and rt.state in ('booting', 'running'):
                time.sleep(nap); nap = min(nap * 1.5, 0.012); seq = rt.frame_seq()      # espera curta logo depois do quadro anterior, mais longa em tela parada
            rgba = q.get('fmt') == 'rgba' and hasattr(rt, 'frame_rgba')        # iDrive 7: o quadro já é RGBA; nada de converter no servidor nem no navegador
            fr = rt.frame_rgba() if rgba else rt.frame_bytes()
            if not fr or fr[0] == since: return 204, b'', 'application/octet-stream', {'X-Frame-Seq': str(seq)}
            return 200, fr[3], 'application/octet-stream', {'X-Frame-Seq': str(fr[0]), 'X-Frame-W': str(fr[1]), 'X-Frame-H': str(fr[2]), 'X-Frame-Fmt': 'rgba' if rgba else 'rgb'}
        if path == 'run/screen.png':
            rt = A.need_rt(); png, seq = rt.screen_png()
            if not png: raise ApiError('sem imagem ainda', 404)
            return 200, png, 'image/png', {'X-Frame-Seq': str(seq)}
        if P[0] == 'input':
            rt = A.need_rt()
            if path == 'input/key': rt.key(int(d['code']), int(d.get('val', 1))); return {'ok': True}
            if path == 'input/rotor': rt.rotor(int(d.get('delta', 0))); return {'ok': True}
            if path == 'input/tilt':
                code = {'up': 9, 'down': 10, 'left': 11, 'right': 12}.get(d.get('dir'))
                if not code: raise ApiError('direção inválida')
                rt.key(code, 1); time.sleep(0.08); rt.key(code, 0); return {'ok': True}
            if path == 'input/click':
                if not hasattr(rt, 'touch'): raise ApiError('toque no display ainda não é suportado pela camada de entrada do guest', 501)
                rt.touch(int(d['x']), int(d['y']), bool(d.get('down')), bool(d.get('move'))); return {'ok': True}
        if path == 'guest/run' and m == 'POST':          # depuração (iDrive 7): roda um comando no shell do guest e devolve a saída
            rt = A.need_rt()
            if not hasattr(rt, 'run_guest'): raise ApiError('só no iDrive 7', 501)
            return {'out': rt.run_guest(str(d.get('cmd', '')), float(d.get('timeout', 20)))}
        if path == 'logs':
            name = q.get('name', 'console'); tail = int(q.get('tail', 200))
            rt = A.rt
            if name == 'guest':
                return {'lines': (list(rt.con)[-tail:] if rt else [])}
            eid = q.get('env') or (rt.id if rt else None) or getattr(A, 'last_id', None)       # sem nada rodando: o último ambiente iniciado nesta sessão
            if not eid: return {'lines': []}
            envd = A.env_dir(eid)
            f = os.path.join(envd, 'logs', {'console': 'console.log', 'qemu': 'qemu.log', 'renderer': 'renderer.log', 'v850': 'v850.log'}.get(name, 'x'))
            if name == 'build':
                b = A.builds.get(eid) or next(iter(A.builds.values()), None)
                return {'lines': b['log'][-tail:] if b else []}
            if not os.path.isfile(f): return {'lines': []}
            with open(f, 'rb') as fh:
                fh.seek(0, 2); sz = fh.tell(); fh.seek(max(0, sz - 65536)); txt = fh.read().decode('utf-8', 'replace')
            return {'lines': [l.rstrip('\r') for l in txt.splitlines()][-tail:]}
        if P[0] == 'phone':
            ph = APP.phone_link()
            try:
                if path == 'phone/start' and m == 'POST': return ph.start()
                if path == 'phone/stop' and m == 'POST': return ph.stop()
            except OSError as e:
                raise ApiError('não consegui abrir as portas %s e %s para o celular (%s)' % (phone.HTTP_PORT, phone.HTTPS_PORT, e.strerror or e), 409)
            return ph.state()
        if P[0] in ('vehicle', 'most'): return self.api_vehicle(m, path, q, d)
        if P[0] == 'can': return self.api_can(m, path, q, d)
        if P[0] == 'gps': return self.api_gps(m, path, q, d)
        if path == 'ssh/info':
            rt = A.need_rt()
            if not rt.ssh: return {'port': rt.env.get('net', {}).get('ssh_port'), 'host': '127.0.0.1', 'user': '', 'key_path': '', 'command': '', 'state': 'down', 'note': 'SSH ainda não iniciado'}
            return rt.ssh.info()
        raise ApiError('rota desconhecida: ' + path, 404)
    def api_vehicle(self, m, path, q, d):
        rt = APP.need_rt()
        if getattr(rt, 'kind', None) != 'cic': raise ApiError('o veículo virtual por MOST/IOC só existe para o CIC', 400)
        if path == 'vehicle/state': return rt.vehicle_state()
        if m != 'POST' and path in ('vehicle/set', 'most/send'): raise ApiError('use POST', 405)
        try:
            if path == 'vehicle/set':
                for k, v in d.items(): rt.set_vehicle(k, v)
                return rt.vehicle_state()
            if path == 'most/send': rt.most_send(d.get('hex', '')); return {'ok': True}
        except ValueError as e: raise ApiError(str(e), 400)
        if path == 'most/seen': return {'fblocks': rt.most_seen()}
        raise ApiError('rota desconhecida', 404)
    def api_can(self, m, path, q, d):
        can = APP.need_can()
        if path == 'can/signals': return can.snapshot()
        if path == 'can/set': can.set_signal(d['name'], d['value']); return {'ok': True}
        if path == 'can/frame':
            can.inject(int(str(d['id']), 16), bytes.fromhex(d['data']), bool(d.get('ext'))); return {'ok': True}
        if path == 'can/frames': return can.frames_since(int(q.get('since', 0)), int(q.get('limit', 200)))
        if path == 'can/scenarios': return can.scenarios()
        if path == 'can/scenario': can.run_scenario(d.get('id')); return {'ok': True}
        if path == 'can/record': r = can.record(bool(d.get('on'))); return {'ok': True, 'file': r}
        if path == 'can/recordings': return {'recordings': can.recordings(), 'replaying': bool(getattr(can, '_replaying', False))}
        if path == 'can/replay': can.replay(d.get('file'), bool(d.get('loop'))); return {'ok': True}
        raise ApiError('rota desconhecida', 404)
    def api_gps(self, m, path, q, d):
        g = APP.need_gps()
        if path == 'gps/state': return g.state()
        if path == 'gps/set': g.set(**d); return {'ok': True}
        if path == 'gps/mode':
            mode = d.pop('mode'); g.set_mode(mode, **d); return {'ok': True}
        if path == 'gps/jump': g.jump(float(d['lat']), float(d['lon'])); return {'ok': True}
        if path == 'gps/route':
            g.load_route(d.get('name') or 'rota', gpx=d.get('gpx'), points=d.get('points'), speed_kmh=float(d.get('speed_kmh', 50)), loop=bool(d.get('loop', True))); return {'ok': True}
        raise ApiError('rota desconhecida', 404)

def serve(host='127.0.0.1', port=8765, open_browser=True):
    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    url = 'http://%s:%d/' % (host, port)
    print('IDEmu: interface em', url, flush=True)
    get_stats()
    import signal
    def _bye(*_):          # terminal fechado / kill: não deixa QEMU, renderizador e sshd para trás
        if getattr(APP, '_phone', None): APP._phone.stop()
        if APP.rt: APP.rt.stop()
        os._exit(0)
    for sg in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sg, _bye)
    if open_browser:
        threading.Timer(0.6, lambda: _open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        if APP.rt: APP.rt.stop()

def _open(url):
    import subprocess
    for app in ('Google Chrome', 'Chromium', 'Microsoft Edge', 'Brave Browser'):
        if os.path.isdir('/Applications/%s.app' % app):
            subprocess.Popen(['open', '-na', app, '--args', '--app=' + url, '--window-size=1400,900']); return
    subprocess.Popen(['open', url])
