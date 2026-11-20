'use strict';
/* IDEmu – seletor de arquivos do servidor, formulário psdzdata e assistente "Novo ambiente". */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;

  /* ================================================================== seletor de arquivos/pastas (no servidor) */
  /** IDE.pickPath({mode:'dir'|'file', start, title, hint}) -> Promise<{path,name,size}|null> */
  IDE.pickPath = function (o) {
    if (window.idemuNative) {      // janela do Electron: diálogo nativo do sistema
      const dir = (o.mode || 'file') === 'dir';
      return window.idemuNative.pick(dir ? 'folder' : 'file', o.title || '', o.start).then((r) => (r && r.path ? { path: r.path, name: r.path.split('/').pop(), size: 0 } : null));
    }
    return new Promise((resolve) => {
      const mode = o.mode || 'file';
      let cur = null, data = null, sel = null, result = null, hideDot = IDE.pref.get('fs.hideDot', true);
      const pathIn = h('input', { class: 'input mono', type: 'text', spellcheck: 'false', 'aria-label': 'Caminho', placeholder: '/caminho/da/pasta' });
      const filterIn = h('input', { class: 'input', type: 'search', placeholder: 'Filtrar por nome…', 'aria-label': 'Filtrar', style: { 'max-width': '220px' } });
      const list = h('div', { class: 'fs-list', role: 'listbox' });
      const status = h('div', { class: 'fs-status' });
      const upBtn = h('button', { class: 'btn', type: 'button', title: 'Subir um nível', onclick: () => data && data.parent && load(data.parent) }, ic('arrowUp', 16), 'Acima');
      const dotChk = h('input', { type: 'checkbox', checked: !hideDot, onchange: (e) => { hideDot = !e.target.checked; IDE.pref.set('fs.hideDot', hideDot); render(); } });
      const body = h('div', { class: 'fs-picker' },
        h('div', { class: 'fs-bar' }, upBtn, pathIn, h('button', { class: 'btn', type: 'button', onclick: () => load(pathIn.value.trim() || '/') }, 'Ir')),
        h('div', { class: 'fs-bar sub' }, filterIn, h('label', { class: 'check' }, dotChk, h('span', null, 'Mostrar ocultos')),
          o.hint ? h('span', { class: 'fs-hint' }, 'Esperado: ', h('code', null, o.hint)) : null),
        list, status);
      const selectBtnLabel = mode === 'dir' ? 'Selecionar esta pasta' : 'Selecionar arquivo';
      const m = IDE.modal({
        title: o.title || (mode === 'dir' ? 'Escolher pasta no servidor' : 'Escolher arquivo no servidor'), size: 'lg', body,
        actions: [{ label: 'Cancelar' }, {
          label: selectBtnLabel, kind: 'primary', icon: 'check', closes: false,
          onClick: (mm) => {
            if (mode === 'dir') { if (!cur) return false; result = { path: cur, name: IDE.baseName(cur), size: 0 }; }
            else { if (!sel) { toast('Clique em um arquivo para selecioná-lo.', 'info'); return false; } result = sel; }
            mm.close();
          },
        }],
        onClose: () => resolve(result),
      });
      const okBtn = m.foot.querySelector('.btn.primary');
      pathIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); load(pathIn.value.trim() || '/'); } });
      filterIn.addEventListener('input', render);

      function join(a, b) { return (a.endsWith('/') ? a : a + '/') + b; }
      function render() {
        IDE.clear(list);
        if (!data) return;
        pathIn.value = data.path;
        upBtn.disabled = !data.parent;
        const f = filterIn.value.trim().toLowerCase();
        let ents = (data.entries || []).slice().sort((a, b) => (b.dir - a.dir) || a.name.localeCompare(b.name, IDE.locale(), { numeric: true }));
        if (hideDot) ents = ents.filter((e) => e.name[0] !== '.');
        if (f) ents = ents.filter((e) => e.name.toLowerCase().includes(f));
        if (!ents.length) list.appendChild(h('div', { class: 'fs-empty' }, f ? 'Nada corresponde ao filtro.' : 'Pasta vazia.'));
        const hint = (o.hint || '').replace(/\.\*$/, '').toLowerCase();
        ents.forEach((e) => {
          const full = join(data.path, e.name);
          const isSel = sel && sel.path === full;
          const disabled = mode === 'dir' && !e.dir;
          const row = h('div', {
            class: 'fs-row' + (e.dir ? ' dir' : '') + (isSel ? ' sel' : '') + (disabled ? ' dim' : '') + (hint && e.name.toLowerCase().startsWith(hint) ? ' match' : ''),
            role: 'option', tabindex: '0', 'aria-selected': isSel ? 'true' : 'false',
          }, ic(e.dir ? 'folder' : 'file', 18), h('span', { class: 'nm', textContent: e.name }), h('span', { class: 'sz' }, e.dir ? '' : IDE.fmtSize(e.size)));
          const act = () => {
            if (e.dir) load(full);
            else if (mode === 'file') { sel = { path: full, name: e.name, size: e.size }; render(); updateStatus(); }
          };
          row.addEventListener('click', act);
          row.addEventListener('dblclick', () => { if (!e.dir && mode === 'file') { sel = { path: full, name: e.name, size: e.size }; result = sel; m.close(); } });
          row.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') act(); });
          list.appendChild(row);
        });
        updateStatus();
      }
      function updateStatus() {
        if (mode === 'dir') status.textContent = cur ? IDE.t('Pasta atual: {path}', { path: cur }) : '';
        else status.textContent = sel ? IDE.t('Selecionado: {name} ({size})', { name: sel.name, size: IDE.fmtSize(sel.size) }) : IDE.t('Clique em um arquivo para selecioná-lo (duplo clique confirma).');
        if (okBtn) okBtn.disabled = mode === 'file' && !sel;
      }
      async function load(p, quiet) {
        try {
          const d = await api('/api/fs/list?' + IDE.qs({ path: p }));
          data = d; cur = d.path; sel = sel && sel.path.startsWith(cur + '/') ? sel : (mode === 'file' ? null : sel);
          IDE.pref.set('fs.last', cur);
          render();
          list.scrollTop = 0;
        } catch (e) {
          if (quiet) { // sobe até achar uma pasta que exista
            const up = p === '~' ? '/' : p.replace(/\/[^/]*\/?$/, '') || '/';
            if (p !== '/') return load(up === p ? '/' : up, true);
          }
          toastErr(e);
        }
      }
      load(o.start || IDE.pref.get('fs.last', null) || '~', true);
    });
  };

  /* ================================================================== formulário da pasta psdzdata */
  IDE.psdzForm = function (o) {
    const input = h('input', { class: 'input mono', type: 'text', spellcheck: 'false', placeholder: '/Users/voce/Downloads/psdzdata', value: IDE.state.settings.psdz_path || '', 'aria-label': 'Caminho da pasta psdzdata', 'data-autofocus': '' });
    const msg = h('div', { class: 'form-msg' });
    const saveBtn = h('button', { class: 'btn primary', type: 'button' }, ic('check', 16), 'Validar e salvar');
    const pickBtn = h('button', { class: 'btn', type: 'button' }, ic('folder', 16), 'Procurar no servidor…');
    function show(kind, text) {
      IDE.clear(msg); if (!text) return;
      msg.className = 'form-msg ' + kind;
      IDE.add(msg, ic(kind === 'ok' ? 'check' : 'alert', 16), h('span', null, text));
    }
    async function save() {
      const p = input.value.trim();
      if (!p) { show('err', 'Informe o caminho da pasta psdzdata.'); input.focus(); return; }
      await IDE.busy(saveBtn, async () => {
        try {
          const r = await post('/api/settings', { psdz_path: p });
          IDE.state.settings.psdz_path = p;
          IDE.catalog = null;
          if (r.psdz_ok) { show('ok', r.message || 'Pasta psdzdata válida.'); toast('Pasta psdzdata configurada.', 'success'); if (o.onSaved) o.onSaved(r); }
          else show('err', r.message || 'Pasta inválida: não encontrei os arquivos esperados do psdzdata.');
          IDE.refreshState().catch(() => {});
        } catch (e) { show('err', e.message); }
      });
    }
    saveBtn.addEventListener('click', save);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } });
    pickBtn.addEventListener('click', async () => {
      const cur = input.value.trim();
      const r = await IDE.pickPath({ mode: 'dir', start: cur || undefined, title: 'Escolher a pasta psdzdata' });
      if (r) { input.value = r.path; save(); }
    });
    return h('div', { class: 'psdz-form' },
      h('p', { class: 'help' }, 'O IDEmu lê os arquivos SWFL do pacote psdzdata (o mesmo usado pelo E-Sys/ISTA). O navegador não mostra caminhos do seu computador, por isso a pasta é escolhida no servidor do IDEmu, que roda na sua máquina.'),
      h('label', { class: 'lbl' }, 'Caminho da pasta'),
      h('div', { class: 'row' }, input, pickBtn),
      msg, h('div', { class: 'row end' }, saveBtn));
  };

  /* ================================================================== assistente */
  const STEPS = [
    { id: 'gen', title: 'Versão do iDrive' }, { id: 'model', title: 'Modelo do carro' }, { id: 'swfl', title: 'Arquivos necessários' },
    { id: 'params', title: 'Parâmetros' }, { id: 'review', title: 'Revisar e criar' },
  ];
  const MONTHS = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
  const NAVI_OPTS = [['ece', 'Europa e resto do mundo (ECE)'], ['us', 'América do Norte (US)'], ['keine_navi', 'Sem navegação']];
  const UNITS = [['metric', 'Métrico (km, °C, L)'], ['imperial', 'Imperial (mi, °F, gal)']];
  const LCI_OPTS = [[0, 'Pré-LCI (facelift anterior)'], [1, 'LCI (facelift)']];
  const MIN_FREE = 1024 * 1024 * 1024;    // o servidor exige 1 GiB livres na pasta escolhida para a VM
  const VIN_RE = /^[A-HJ-NPR-Z0-9]{17}$/;
  const ROLE_ICON = { os: 'cpu', brand: 'layers', hmi: 'menu' };
  const ROLE_ORDER = ['os', 'brand', 'hmi'];

  let W = null;
  function fresh() {
    return { step: 0, started: false, gen: 'id6', role: 'hu', home: IDE.pref.get('vm.home', '') || '', space: null, found: {}, scan: null, series: null, chassis: null, swfl: {}, coding: null, net: { ssh_port: 2222, can_port: 29536, gps_port: 29537 },
      name: '', nameTouched: false, phase: 'edit', env: null, build: null, cat: null };
  }
  IDE.wizard = { reset() { W = fresh(); } };

  /* ---- derivados do catálogo ---- */
  const cat = () => W.cat || { series: [], roles: [], by_series: {} };
  const seriesObj = () => cat().series.find((s) => s.id === W.series) || null;
  const chassisObj = () => { const s = seriesObj(); return s ? (s.chassis || []).find((c) => c.code === W.chassis) || null : null; };
  const brand = () => { const c = chassisObj(); return c ? c.brand : null; };
  function needId(role) {
    const r = ((cat().by_series || {})[W.series] || {}).roles;
    const v = r ? r[role] : null;
    if (v && typeof v === 'object') return v[brand()] || null;
    return v || null;
  }
  const genObj = () => ((cat().generations || []).find((g) => g.id === W.gen)) || null;
  function roleList() {
    const roles = cat().roles || [];
    const extra = [...new Set(roles.map((r) => r.role))].filter((r) => !ROLE_ORDER.includes(r));
    return ROLE_ORDER.concat(extra).filter((role) => needId(role) || roles.some((r) => r.role === role)).map((role) => {
      const id = needId(role);
      const exact = id ? roles.find((r) => r.role === role && r.id === id) : null;
      const def = exact || roles.find((r) => r.role === role) || {};
      let files = (def.files || []).slice();
      if (!exact && id) files = files.filter((f) => String(f.file).includes(id));
      ((W.found || {})[(id || def.id || '').toLowerCase()] || []).forEach((f) => { if (!files.some((x) => x.path === f.path)) files.push(f); });
      files = files.slice().sort((a, b) => IDE.verCmp(b.version, a.version));
      return { role, id: id || def.id || '', label: def.label || role, help: def.help || '', required: def.required !== false, files, approx_mb: def.approx_mb || null };
    });
  }
  const roleKey = (r) => r.role + ':' + r.id;
  function ensureSwfl() {
    roleList().forEach((r) => {
      const cur = W.swfl[r.role];
      if (cur && cur.key === roleKey(r)) return;
      delete W.swfl[r.role];
      if (r.files.length) { const f = r.files[0]; W.swfl[r.role] = { key: roleKey(r), path: f.path, file: f.file, size: f.size, version: f.version, custom: false }; }
    });
  }
  function opts(list, fallback) { return (list && list.length ? list : fallback).map((x) => (typeof x === 'string' ? { code: x, name: x } : x)); }
  function initCoding() {
    if (W.coding) return;
    const c = cat();
    const pick = (list, pref) => { const l = opts(list, []); return (l.find((x) => x.code === pref) || l[0] || {}).code || pref; };
    W.coding = {
      language: pick(c.languages, IDE.lang() === 'pt' ? 'pt_BR' : 'en_GB'), country: pick(c.countries, IDE.lang() === 'pt' ? 'BR' : 'GB'), units: 'metric', vin: '', year: 2017, month: 7, lci: 1,
      display: pick(c.displays, '10_25_1440x540'), hmi_version: pick(c.hmi_versions, (genObj() || {}).hmi_version || 'id6_light'), navi: 'ece', hu_variant: 'professional',
    };
    if (W.vin && W.vin.env && W.vin.env.coding) Object.assign(W.coding, W.vin.env.coding);         // carro vindo do VIN (etapa 1)
  }
  function vinError(v) {
    if (!v) return IDE.t('Informe o VIN (17 caracteres).');
    if (/[^A-HJ-NPR-Z0-9]/.test(v)) return IDE.t('Use apenas letras e números, sem as letras I, O e Q.');
    if (v.length !== 17) return IDE.t('O VIN precisa ter 17 caracteres (tem {n}).', { n: v.length });
    return null;
  }
  function portErrors() {
    const n = W.net, errs = {}, vals = [];
    [['ssh_port', 'SSH'], ['can_port', 'CAN'], ['gps_port', 'GPS']].forEach(([k, l]) => {
      const v = n[k];
      if (!Number.isInteger(v) || v < 1024 || v > 65535) errs[k] = IDE.t('Use uma porta entre 1024 e 65535.');
      vals.push([k, v]);
    });
    vals.forEach(([k, v]) => { if (!errs[k] && vals.some(([k2, v2]) => k2 !== k && v2 === v)) errs[k] = IDE.t('As três portas precisam ser diferentes.'); });
    return errs;
  }
  function defaultName() { const c = chassisObj(); return c ? c.code + ' ' + IDE.brandName(c.brand) : ''; }

  /** Retorna lista de pendências do passo (vazia = ok). */
  function problems(i) {
    const id = STEPS[i].id, out = [];
    if (id === 'gen') {
      if (!genObj() || !genObj().supported) out.push('escolha a versão do iDrive');
      if (W.home && W.space && (!W.space.writable || W.space.free < MIN_FREE)) out.push('pasta da VM com espaço e permissão');
      if (genObj() && genObj().direct && !(W.pkgOk && W.pkgOk[genObj().direct])) out.push('arquivos do sistema');
    }
    else if (id === 'model') { if (!W.series) out.push('escolha a série'); else if (!W.chassis) out.push('escolha o chassi'); }
    else if (id === 'swfl') {
      roleList().forEach((r) => { if (r.required && !W.swfl[r.role]) out.push(IDE.t('arquivo "{label}"', { label: IDE.t(r.label) })); });
    } else if (id === 'params') {
      if (!W.name.trim()) out.push('nome do ambiente');
      const e = vinError(W.coding.vin); if (e) out.push('VIN válido');
      if (Object.keys(portErrors()).length) out.push('portas válidas');
    }
    return out;
  }

  /* ---- montagem ---- */
  function mount(root) {
    if (!W) W = fresh();
    const stepper = h('div', { class: 'wz-head card' });
    const body = h('div', { class: 'wz-body card' });
    const foot = h('div', { class: 'wz-foot' });
    root.appendChild(h('div', { class: 'page narrow' },
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Novo ambiente'), h('p', { class: 'sub' }, 'Siga as etapas para montar um carro virtual.'))),
      stepper, body, foot));
    let stopBuildLoop = null, dead = false;
    let vinEl = null;          // painel do VIN da etapa 1 (um por montagem da tela)

    async function loadCat() {
      try { W.cat = await IDE.loadCatalog(true); } catch (e) { toastErr(e); W.cat = W.cat || null; }
      if (dead) return;
      W.started = true;
      ensureSwfl(); render();
    }

    function render() {
      if (dead) return;
      renderStepper(); renderBody(); renderFoot();
      const lg = document.getElementById('wb-log'); if (lg) lg.scrollTop = lg.scrollHeight;
      if (W.phase === 'building' && !stopBuildLoop) monitorBuild();
    }
    function renderStepper() {
      IDE.clear(stepper);
      const total = STEPS.length, pct = W.phase === 'done' ? 100 : ((W.step + 1) / total) * 100;
      IDE.add(stepper, 
        h('ol', { class: 'stepper' }, STEPS.map((s, i) => {
          const done = i < W.step || W.phase === 'done';
          const li = h('li', { class: (done ? 'done ' : '') + (i === W.step && W.phase !== 'done' ? 'cur' : '') },
            h('button', { type: 'button', class: 'st', disabled: !(W.phase === 'edit' && i < W.step), onclick: () => { W.step = i; render(); } },
              h('span', { class: 'dot' }, done ? ic('check', 14) : String(i + 1)), h('span', { class: 'lbl' }, s.title)));
          return li;
        })),
        h('div', { class: 'wz-prog' }, h('div', { class: 'bar' }, h('i', { style: { width: pct + '%' } })),
          h('span', { class: 'wz-prog-txt' }, W.phase === 'edit' ? IDE.t('Etapa {n} de {total} · {title}', { n: W.step + 1, total, title: IDE.t(STEPS[W.step].title) }) : (W.phase === 'done' ? 'Concluído' : 'Criando ambiente…'))));
    }
    function renderBody() {
      IDE.clear(body);
      if (W.phase !== 'edit') { body.appendChild(buildPanel()); return; }
      const id = STEPS[W.step].id;
      if (!W.cat) { body.appendChild(h('div', { class: 'loading' }, 'Carregando catálogo…')); return; }
      if (id === 'gen') body.appendChild(stepGen());
      else if (id === 'model') body.appendChild(stepModel());
      else if (id === 'swfl') body.appendChild(stepFiles());
      else if (id === 'params') body.appendChild(stepParams());
      else body.appendChild(stepReview());
    }
    function renderFoot() {
      IDE.clear(foot);
      if (W.phase === 'edit') {
        const last = W.step === STEPS.length - 1;
        const pr = problems(W.step);
        const direct = STEPS[W.step].id === 'gen' && genObj() && genObj().direct;   // iDrive 8: tudo vem da PSdZData, não há o que escolher
        const next = h('button', { class: 'btn primary lg', type: 'button', disabled: pr.length > 0, onclick: () => (last || direct ? createAndBuild() : go(1)) },
          last || direct ? [ic('wrench', 18), 'Criar e compilar'] : ['Avançar', ic('chevR', 18)]);
        IDE.add(foot, 
          h('button', { class: 'btn ghost', type: 'button', onclick: () => IDE.go('ambientes') }, 'Cancelar'),
          h('div', { class: 'spacer' }),
          pr.length ? h('div', { class: 'missing' }, ic('alert', 16), h('span', null, IDE.t('Falta: {list}', { list: pr.map((x) => IDE.t(x)).join(', ') }))) : null,
          W.step > 0 ? h('button', { class: 'btn', type: 'button', onclick: () => go(-1) }, ic('chevL', 18), 'Voltar') : null,
          next);
      } else if (W.phase === 'done') {
        IDE.add(foot, h('div', { class: 'spacer' }),
          h('button', { class: 'btn', onclick: () => { IDE.wizard.reset(); IDE.go('ambientes'); } }, 'Voltar aos ambientes'),
          h('button', { class: 'btn success lg', onclick: (ev) => startNow(ev.currentTarget) }, ic('play', 18), 'Iniciar agora'));
      } else if (W.phase === 'builderr') {
        IDE.add(foot, h('div', { class: 'spacer' }),
          h('button', { class: 'btn', onclick: () => { IDE.wizard.reset(); IDE.go('ambientes'); } }, 'Ver ambientes'),
          h('button', { class: 'btn primary lg', onclick: retryBuild }, ic('refresh', 18), 'Tentar compilar de novo'));
      } else {
        IDE.add(foot, h('div', { class: 'spacer' }), h('span', { class: 'muted small' }, 'Você pode sair desta tela: o build continua no servidor.'),
          h('button', { class: 'btn', onclick: () => IDE.go('ambientes') }, 'Ver ambientes'));
      }
    }
    function go(d) {
      const n = W.step + d;
      if (n < 0 || n >= STEPS.length) return;
      if (d > 0 && problems(W.step).length) return;
      W.step = n;
      if (STEPS[n].id === 'swfl') ensureSwfl();
      if (STEPS[n].id === 'params') { initCoding(); if (!W.nameTouched) W.name = defaultName(); }
      render(); window.scrollTo(0, 0);
    }
    const refreshFoot = () => { if (!dead && W.phase === 'edit') renderFoot(); };

    /* ---------------- etapa 1: versão do iDrive ---------------- */
    function levelBlock(g) {
      const lv = g.level; if (!lv) return null;
      const ST = { full: ['✓', 'Funciona'], half: ['◐', 'Funciona em parte'], none: ['✕', 'Não funciona'] };
      const cls = lv.pct >= 70 ? 'hi' : lv.pct >= 45 ? 'mid' : 'lo';
      return h('span', { class: 'glv' },
        h('span', { class: 'glv-top' }, h('span', { class: 'glv-t' }, 'Nível de funcionalidade'), h('b', { class: 'glv-n ' + cls }, IDE.t('{pct}% · {name}', { pct: lv.pct, name: IDE.t(lv.name) }))),
        h('span', { class: 'glv-bar' }, h('i', { class: cls, style: { width: lv.pct + '%' } })),
        h('span', { class: 'glv-list' }, lv.features.map((f) => h('span', { class: 'glv-i ' + f.state, title: f.note ? IDE.t(f.note) : IDE.t(ST[f.state][1]) },
          h('span', { class: 'glv-g', 'aria-hidden': 'true' }, ST[f.state][0]), h('span', { class: 'glv-l' }, IDE.t(f.label)), h('span', { class: 'sr-only' }, ': ' + IDE.t(ST[f.state][1]))))));
    }
    function pickHome() {
      IDE.pickPath({ mode: 'dir', start: W.home || undefined, title: 'Escolher a pasta da máquina virtual' }).then((r) => { if (r) { W.home = r.path; IDE.pref.set('vm.home', r.path); loadSpace(); render(); } });
    }
    function useDefaultHome() { W.home = ''; W.space = null; loadSpace(); render(); }
    async function loadSpace() {
      const want = W.home;
      try { const sp = await api('/api/fs/space?' + IDE.qs({ path: want || cat().envs_dir || '' })); if (W.home === want) { W.space = sp; if (!dead) render(); } }
      catch (e) {
        if (W.home !== want) return;
        W.space = null;
        if (want) { W.home = ''; IDE.pref.set('vm.home', ''); toast('A pasta escolhida antes não existe mais: usando a pasta padrão.', 'info'); loadSpace(); }
        if (!dead) render();
      }
    }
    function homeBlock() {
      const sp = W.space, low = sp && sp.free < 4 * MIN_FREE, bad = sp && W.home && (!sp.writable || sp.free < MIN_FREE);
      const shown = W.home || cat().envs_dir || '';
      const direct = genObj() && genObj().direct;
      return h('section', { class: 'vmhome' },
        h('h3', null, 'Onde a máquina virtual fica'),
        h('p', { class: 'help' }, 'Os discos, os logs e o estado salvo do ambiente ficam numa subpasta com o nome do ambiente, dentro da pasta escolhida. Pode ser outro disco ou um disco externo (ele precisa estar conectado para iniciar o ambiente).'),
        h('div', { class: 'vmhome-row' },
          h('div', { class: 'vmhome-path' }, ic('folder', 18), h('code', { class: 'mono' }, shown), W.home ? null : h('span', { class: 'muted small' }, ' · ' + IDE.t('pasta padrão do IDEmu'))),
          h('button', { class: 'btn', type: 'button', onclick: pickHome }, ic('folder', 16), W.home ? 'Trocar pasta…' : 'Escolher pasta…'),
          W.home ? h('button', { class: 'btn ghost', type: 'button', onclick: useDefaultHome }, 'Usar a pasta padrão') : null),
        sp ? h('div', { class: 'vmhome-free' + (bad ? ' bad' : low ? ' low' : '') }, ic(bad ? 'alert' : 'info', 14),
          h('span', null, !sp.writable ? IDE.t('Sem permissão para gravar nesta pasta.') : IDE.t('{size} livres neste disco.', { size: IDE.fmtSize(sp.free) }) + (sp.free < MIN_FREE ? ' ' + IDE.t('É preciso ao menos 1 GB.') : (low ? ' ' + IDE.t('O iDrive 5 e 6 usam cerca de 3 GB por ambiente.') : '')))) : null,
        direct ? h('p', { class: 'help' }, 'No iDrive 7 e 8 a imagem do sistema (alguns GB) é única e compartilhada: ela fica na pasta do IDEmu. Na pasta escolhida ficam os dados e os logs do ambiente.') : null);
    }
    // CIC: o HMI fala o idioma da interface do IDEmu (os que o CIC não tem ficam em inglês; ver LANGUAGES em idemu/cic.py)
    const CIC_LANG = { en: 'en_GB', pt: 'pt_PT', es: 'es_ES', fr: 'fr_FR', de: 'de_DE', it: 'it_IT', tr: 'tr_TR', ru: 'ru_RU' };
    function roleBlock() {
      const opts = [['hu', 'Tela central', '1920 × 720 · o menu inicial do iDrive 7'], ['rse', 'Banco traseiro (RSE)', '1920 × 1080 · a tela de entretenimento dos bancos de trás']];
      return h('section', { class: 'vmhome' },
        h('h3', null, 'Qual tela do iDrive 7?'),
        h('p', { class: 'help' }, 'O iDrive 7 tem duas telas com o mesmo software. Cada ambiente emula uma delas.'),
        h('div', { class: 'vmhome-row' }, opts.map(([id, t, sub]) => h('button', { type: 'button', class: 'opt' + (W.role === id ? ' sel' : ''), onclick: () => { W.role = id; render(); } },
          h('span', { class: 'opt-main' }, h('b', null, t), h('span', null, sub)), W.role === id ? ic('check', 16) : null))));
    }
    function pkgBlock() {
      const k = genObj() && genObj().direct; if (!k) return null;
      if (!W.pkgEl || W.pkgEl.kind !== k) {
        const el = IDE.pkgPanel(k, { onChange: (st) => { W.pkgOk = W.pkgOk || {}; const was = W.pkgOk[k]; W.pkgOk[k] = st.ok; if (was !== st.ok) refreshFoot(); } });
        el.kind = k; W.pkgEl = el;
      }
      return h('section', { class: 'vmhome' }, h('h3', null, 'Arquivos do sistema'),
        h('p', { class: 'help' }, 'O emulador precisa destes arquivos SWFL. Procure cada um pelo nome, escolha vários de uma vez ou aponte uma pasta e o app acha sozinho. A PSdZData inteira também funciona.'), W.pkgEl);
    }
    function stepGen() {
      const gens = cat().generations || [];
      const cards = gens.map((g) => h('button', { type: 'button', class: 'gen' + (W.gen === g.id ? ' sel' : ''), disabled: !g.supported,
          onclick: () => { if (W.gen !== g.id) { W.gen = g.id; W.coding = null; render(); } } },
        W.gen === g.id ? h('span', { class: 'gchk' }, ic('check', 20)) : null,
        h('span', { class: 'gn' }, g.name), h('span', { class: 'gs' }, g.sub),
        levelBlock(g),
        g.supported ? null : h('span', { class: 'gb' }, IDE.badge('Ainda sem imagem', 'muted'))));
      if (!W.space && !W.spaceAsked) { W.spaceAsked = true; loadSpace(); }
      if (!vinEl) vinEl = IDE.vinPanel({ value: W.vin ? W.vin.vin : '', hint: 'Opcional. O IDEmu reconhece o modelo, o ano e a central do carro e preenche as etapas seguintes.', useLabel: 'Usar este carro', onUse: useVin });
      return h('div', { class: 'step' },
        h('section', { class: 'vmhome vin-sec' }, h('h3', null, ic('target', 16), ' ', IDE.t('Tem o VIN do seu carro?')), vinEl,
          W.vin ? h('div', { class: 'note ok' }, ic('check', 16), h('span', null, IDE.t('Usando o carro do VIN {vin}: {car}.', { vin: W.vin.vin, car: [W.vin.chassis, W.vin.model_year].filter(Boolean).join(' ') }))) : null),
        h('h2', null, 'Qual iDrive você quer emular?'),
        h('p', { class: 'help' }, 'A escolha define quais arquivos do sistema serão pedidos. Você não precisa ter a PSdZData inteira: só os arquivos que aparecerem na etapa 3. O nível de funcionalidade mostra o que já funciona em cada versão.'),
        h('div', { class: 'gen-grid' }, cards), genObj() && genObj().direct === 'mgu7' ? roleBlock() : null, pkgBlock(), homeBlock());
    }

    function useVin(d) {
      const g = d.generation, gens = cat().generations || [];
      if (!gens.some((x) => x.id === g && x.supported)) { toast(IDE.t('O IDEmu ainda não emula o {gen}.', { gen: IDE.genName(g) }), 'error'); return; }
      W.vin = d; W.gen = g; W.coding = null;
      const sug = d.env || {};
      if (g === 'id5' || g === 'id6') {
        const s = cat().series.find((x) => x.id === sug.series);
        if (s && s.chassis.some((c) => c.code === sug.chassis)) { W.series = s.id; W.chassis = sug.chassis; W.swfl = {}; }
        else toast(IDE.t('O chassi {c} não está na sua PSdZData: escolha o modelo na etapa 2.', { c: sug.chassis || '?' }), 'info');
      }
      if (!W.nameTouched && sug.name) W.name = sug.name;
      initCoding();
      toast(IDE.t('Carro do VIN aplicado: {gen}.', { gen: IDE.genName(g) }), 'success');
      render();
    }

    /* ---------------- etapa 2: modelo ---------------- */
    function stepModel() {
      const c = cat();
      const s = seriesObj(), ch = chassisObj();
      const colSeries = h('div', { class: 'col' }, h('h3', null, '1. Série'),
        c.series.map((it) => h('button', { type: 'button', class: 'opt' + (W.series === it.id ? ' sel' : ''), onclick: () => { if (W.series !== it.id) { W.series = it.id; W.chassis = null; W.swfl = {}; render(); } } },
          h('span', { class: 'opt-main' }, h('b', null, it.id), h('span', null, it.name)), W.series === it.id ? ic('check', 16) : null)));
      const colChassis = h('div', { class: 'col' }, h('h3', null, '2. Chassi'),
        s ? s.chassis.map((it) => h('button', { type: 'button', class: 'opt' + (W.chassis === it.code ? ' sel' : ''), onclick: () => { W.chassis = it.code; W.swfl = {}; if (!W.nameTouched) W.name = defaultName(); render(); } },
          h('span', { class: 'opt-main' }, h('b', null, it.code), h('span', null, it.name)), IDE.badge(IDE.brandName(it.brand), 'brand-' + it.brand)))
          : h('div', { class: 'placeholder' }, 'Escolha uma série para ver os chassis.'));
      const colBrand = h('div', { class: 'col' }, h('h3', null, '3. Marca'),
        ch ? h('div', { class: 'brand-card' },
          h('div', { class: 'brand-big brand-' + ch.brand }, IDE.brandName(ch.brand)),
          h('p', { class: 'small muted' }, 'A marca é definida pelo chassi e determina o arquivo de "Dados da marca".'),
          h('dl', { class: 'kv one' },
            h('div', null, h('dt', null, 'Série'), h('dd', null, s.id + ' – ' + IDE.t(s.name))),
            h('div', null, h('dt', null, 'Chassi'), h('dd', null, ch.code + ' – ' + ch.name)),
            ch.ego_model ? h('div', null, h('dt', null, 'Modelo ego'), h('dd', { class: 'mono' }, ch.ego_model)) : null,
            h('div', null, h('dt', null, 'Arquivos necessários'), h('dd', { class: 'mono small' }, roleList().map((r) => 'swfl_' + r.id).join('  ')))))
          : h('div', { class: 'placeholder' }, 'Escolha o chassi para ver a marca.'));
      return h('div', { class: 'step' }, h('h2', null, 'Modelo do carro'),
        h('p', { class: 'help' }, 'Escolha a série e o chassi do carro que será emulado. O catálogo vem do servidor.'),
        h('div', { class: 'model-grid' }, colSeries, colChassis, colBrand));
    }

    /* ---------------- etapa 3: arquivos necessários ---------------- */
    const needIds = () => roleList().map((r) => r.id).filter(Boolean);
    async function pickNative(kind, prompt, start) {
      if (window.idemuNative) { try { const r = await window.idemuNative.pick(kind, prompt, start); return { native: true, path: r.path || null }; } catch (e) { /* cai no seletor do servidor */ } }
      try { const r = await post('/api/pick', { kind, prompt, start }); return { native: true, path: r.path || null }; }
      catch (e) { return { native: false }; }
    }
    async function scanFolder(path) {
      W.scanning = true; render();
      try {
        const r = await post('/api/scan', { path, ids: needIds() });
        W.found = r.files || {}; W.scan = { path: r.path, timeout: r.timeout };
        roleList().forEach((rl) => { const cur = W.swfl[rl.role]; const f = rl.files[0]; if ((!cur || !cur.custom) && f) W.swfl[rl.role] = { key: roleKey(rl), path: f.path, file: f.file, size: f.size, version: f.version, custom: false }; });
        const n = roleList().filter((rl) => W.swfl[rl.role]).length;
        toast(n === roleList().length ? IDE.t('Encontrei os {n} arquivos.', { n }) : IDE.t('Encontrei {n} de {total} arquivos.', { n, total: roleList().length }), n === roleList().length ? 'success' : 'info');
      } catch (e) { toastErr(e); }
      W.scanning = false; render();
    }
    async function browseFolder() {
      const start = (W.scan && W.scan.path) || IDE.state.settings.psdz_path || undefined;
      const n = await pickNative('folder', IDE.t('Escolha a pasta que contém os arquivos swfl_… (pode ser a pasta psdzdata inteira)'), start);
      let path = n.path;
      if (!n.native) { const r = await IDE.pickPath({ mode: 'dir', start, title: IDE.t('Escolher a pasta com os arquivos') }); path = r && r.path; }
      if (path) scanFolder(path);
    }
    function stepFiles() {
      ensureSwfl();
      const roles = roleList();
      const have = roles.filter((r) => W.swfl[r.role]).length;
      const total = roles.length;
      const totalMb = roles.reduce((a, r) => a + (r.approx_mb || 0), 0);
      const allOk = have === total && total > 0;
      const banner = h('div', { class: 'need-banner' + (allOk ? ' ok' : '') },
        h('div', { class: 'ico-big' }, ic(allOk ? 'check' : 'folder', 22)),
        h('div', { class: 'nb-t' },
          h('b', null, allOk ? IDE.t('Tudo certo: {n} de {total} arquivos escolhidos', { n: have, total }) : IDE.t('Você precisa de {total} arquivos', { total })),
          h('span', null, W.scan ? IDE.t('Procurei em {path}', { path: W.scan.path }) + (W.scan.timeout ? ' ' + IDE.t('(a busca foi interrompida por demorar demais)') : '')
            : (totalMb ? IDE.t('Cerca de {gb} GB no total. Aponte a pasta onde eles estão e eu escolho sozinho, ou escolha um por um.', { gb: (totalMb / 1024).toFixed(1).replace('.', IDE.lang() === 'pt' ? ',' : '.') }) : 'Aponte a pasta onde eles estão e eu escolho sozinho, ou escolha um por um.'))),
        h('button', { class: 'btn primary', type: 'button', disabled: !!W.scanning, onclick: browseFolder }, ic('folder', 16), W.scanning ? 'Procurando…' : (W.scan ? 'Procurar em outra pasta…' : 'Procurar pasta…')));
      const items = roles.map((r) => {
        const sel = W.swfl[r.role];
        const pattern = 'swfl_' + r.id + '.bin.<' + IDE.t('versão') + '>';
        const warnName = sel && sel.file && r.id && !sel.file.toLowerCase().startsWith('swfl_' + r.id.toLowerCase());
        const versions = r.files.length > 1 ? h('select', { class: 'input sm', 'aria-label': 'Versão', onchange: (e) => { const f = r.files.find((x) => x.path === e.target.value); if (f) { W.swfl[r.role] = { key: roleKey(r), path: f.path, file: f.file, size: f.size, version: f.version, custom: false }; render(); } } },
          r.files.map((f, i) => h('option', { value: f.path, selected: !!sel && sel.path === f.path }, IDE.t('Versão') + ' ' + (f.version || '–') + ' · ' + IDE.fmtSize(f.size) + (i === 0 ? ' · ' + IDE.t('Mais nova') : '')))) : null;
        return h('div', { class: 'need ' + (sel ? 'ok' : 'missing') },
          h('div', { class: 'role-ico' }, ic(ROLE_ICON[r.role] || 'file', 22)),
          h('div', { class: 'nd' },
            h('h3', null, r.label),
            h('div', { class: 'fname' }, pattern),
            r.help ? h('div', { class: 'why' }, IDE.t(r.help) + (r.approx_mb ? ' · ' + IDE.t('cerca de {mb} MB', { mb: r.approx_mb }) : '')) : null,
            sel ? h('div', { class: 'got' }, ic('check', 14), h('span', { class: 'mono' }, sel.file + (sel.size ? ' · ' + IDE.fmtSize(sel.size) : ''))) : null,
            sel ? h('div', { class: 'why mono' }, sel.path) : null,
            warnName ? h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, IDE.t('O nome do arquivo escolhido não começa com swfl_{id}. Confira se é o arquivo certo.', { id: r.id }))) : null),
          h('div', { class: 'vers' }, versions,
            h('button', { class: 'btn' + (sel ? '' : ' primary-o'), type: 'button', onclick: () => pickFile(r) }, ic('file', 16), sel ? 'Trocar arquivo…' : 'Escolher arquivo…')));
      });
      const saved = IDE.state.settings.psdz_path;
      return h('div', { class: 'step' }, h('h2', null, 'Arquivos necessários'),
        h('p', { class: 'help' }, IDE.t('Para {name}, o emulador usa estes arquivos SWFL do pacote de software da BMW (PSdZData).', { name: (genObj() || {}).name || 'iDrive' })),
        banner, h('div', { class: 'need-list' }, items),
        saved ? h('div', { class: 'need-more' }, ic('info', 14), h('span', null, IDE.t('Usando também a sua pasta salva: {path}', { path: saved }))) : null);
    }
    async function pickFile(r) {
      const sel = W.swfl[r.role];
      const start = sel && sel.path ? sel.path.replace(/\/[^/]*$/, '') || '/' : ((W.scan && W.scan.path) || IDE.state.settings.psdz_path || undefined);
      const n = await pickNative('file', IDE.t('Escolha o arquivo swfl_{id}.bin.…', { id: r.id }), start);
      let res = null;
      if (n.native) { if (n.path) res = { path: n.path, name: n.path.split('/').pop(), size: 0 }; }
      else res = await IDE.pickPath({ mode: 'file', start, title: IDE.t('Escolher arquivo – {label}', { label: IDE.t(r.label) }), hint: 'swfl_' + r.id + '.bin.*' });
      if (!res) return;
      W.swfl[r.role] = { key: roleKey(r), path: res.path, file: res.name, size: res.size, version: (res.name.match(/\.bin\.(.+)$/) || [])[1] || '', custom: true };
      render();
    }

    /* ---------------- etapa 4: parâmetros ---------------- */
    function stepParams() {
      initCoding();
      const c = W.coding, ct = cat();
      const sel = (key, list, conv) => h('select', { class: 'input', onchange: (e) => { c[key] = conv ? conv(e.target.value) : e.target.value; } },
        list.map(([v, l]) => h('option', { value: v, selected: String(c[key]) === String(v) }, l)));
      const lang = opts(ct.languages, [{ code: 'pt_BR', name: 'Português (Brasil)' }]).map((x) => [x.code, x.name]);
      const ctry = opts(ct.countries, [{ code: 'BR', name: 'Brasil' }]).map((x) => [x.code, x.name]);
      const disp = opts(ct.displays, [{ code: '10_25_1440x540', name: '10,25" 1440x540' }]).map((x) => [x.code, x.name]);
      const hmiv = opts(ct.hmi_versions, [{ code: 'id6_light', name: 'iDrive 6 (tiles)' }]).map((x) => [x.code, x.name]);
      const naviList = (ct.navi && ct.navi.length) ? opts(ct.navi, []).map((x) => [x.code, x.name]) : NAVI_OPTS;
      const huPick = IDE.huVariantPicker(() => c.hu_variant || 'professional', (id) => {
        const v = (ct.hu_variants || []).find((x) => x.id === id); c.hu_variant = id;
        if (v) { c.display = v.display; if (v.navi && c.navi === 'keine_navi') c.navi = c.country === 'US' ? 'us' : 'ece'; }
        render();
      });
      const years = []; for (let y = 2022; y >= 2012; y--) years.push([y, String(y)]);
      const months = MONTHS.map((m, i) => [i + 1, String(i + 1).padStart(2, '0') + ' – ' + IDE.t(m)]);

      const nameErr = h('div', { class: 'ferr' });
      const nameIn = h('input', { class: 'input', type: 'text', value: W.name, maxlength: 60, 'aria-label': 'Nome do ambiente' });
      nameIn.addEventListener('input', () => { W.name = nameIn.value; W.nameTouched = true; nameErr.textContent = W.name.trim() ? '' : IDE.t('Dê um nome ao ambiente.'); refreshFoot(); });

      const vinErr = h('div', { class: 'ferr' });
      const vinIn = h('input', { class: 'input mono', type: 'text', value: c.vin, maxlength: 17, spellcheck: 'false', autocapitalize: 'characters', placeholder: '17 caracteres, ex.: WBA8A9C50GK000001', 'aria-label': 'VIN' });
      const vinCount = h('span', { class: 'count' }, c.vin.length + '/17');
      function vinUpdate(touch) {
        const v = vinIn.value.toUpperCase().replace(/\s/g, ''); vinIn.value = v; c.vin = v; vinCount.textContent = v.length + '/17';
        const e = vinError(v);
        vinErr.textContent = (v.length || touch) && e ? e : '';
        vinIn.classList.toggle('bad', !!(v.length && e && (v.length >= 17 || /[^A-HJ-NPR-Z0-9]/.test(v))));
        vinIn.classList.toggle('good', !e);
        refreshFoot();
      }
      vinIn.addEventListener('input', () => vinUpdate(false));
      vinIn.addEventListener('blur', () => vinUpdate(true));
      const genBtn = h('button', { class: 'btn', type: 'button', title: 'Gerar um VIN de exemplo', onclick: () => {
        const al = 'ABCDEFGHJKLMNPRSTUVWXYZ0123456789';
        let v = (brand() === 'mini' ? 'WMW' : (brand() === 'rr' ? 'SCA' : 'WBA')) + 'A';
        while (v.length < 17) v += al[Math.floor(Math.random() * al.length)];
        vinIn.value = v; vinUpdate(true);
      } }, ic('refresh', 16), 'Gerar exemplo');

      const portErrEls = {};
      const portIn = (key, label) => {
        const err = portErrEls[key] = h('div', { class: 'ferr' });
        const inp = h('input', { class: 'input mono', type: 'number', min: 1024, max: 65535, value: W.net[key], 'aria-label': IDE.t('Porta {label}', { label }) });
        inp.addEventListener('input', () => { W.net[key] = inp.value === '' ? NaN : Number(inp.value); const e = portErrors(); Object.keys(portErrEls).forEach((k) => { portErrEls[k].textContent = e[k] || ''; }); refreshFoot(); });
        return h('div', { class: 'field' }, h('label', { class: 'lbl' }, label), inp, err);
      };

      const form = h('div', { class: 'step' }, h('h2', null, 'Parâmetros do carro'),
        h('p', { class: 'help' }, 'Codificação e rede do ambiente. Tudo isso pode ser ajustado depois, sem refazer o build completo.'),
        h('fieldset', null, h('legend', null, 'Identificação'),
          h('div', { class: 'grid-2' },
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Nome do ambiente'), nameIn, nameErr),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'VIN (17 caracteres)'), h('div', { class: 'row tight' }, vinIn, genBtn), h('div', { class: 'row between' }, vinErr, vinCount)))),
        h('fieldset', null, h('legend', null, 'Tipo de head unit'),
          h('p', { class: 'help' }, 'A PSdZData traz o firmware do NBT Evo; o Business e o EntryNav são reproduzidos pela codificação (display, navegação e toque), como nos carros que saíam com essas unidades.'), huPick),
        h('fieldset', null, h('legend', null, 'Região'),
          h('div', { class: 'grid-3f' },
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Idioma'), sel('language', lang)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'País'), sel('country', ctry)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Unidades'), sel('units', UNITS)))),
        h('fieldset', null, h('legend', null, 'Veículo e tela'),
          h('div', { class: 'grid-3f' },
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Ano de produção'), sel('year', years, Number)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Mês de produção'), sel('month', months, Number)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Fase (LCI)'), sel('lci', LCI_OPTS, Number)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Tipo de display'), sel('display', disp)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Versão do HMI'), sel('hmi_version', hmiv)),
            h('div', { class: 'field' }, h('label', { class: 'lbl' }, 'Navegação'), sel('navi', naviList)))),
        h('fieldset', null, h('legend', null, 'Portas no seu computador (loopback)'),
          h('div', { class: 'grid-3f' }, portIn('ssh_port', 'SSH'), portIn('can_port', 'CAN'), portIn('gps_port', 'GPS'))));
      setTimeout(() => { if (c.vin) vinUpdate(false); }, 0);
      return form;
    }

    /* ---------------- etapa 5: revisão ---------------- */
    function stepReview() {
      const c = W.coding, s = seriesObj(), ch = chassisObj();
      const row = (k, v, mono) => h('div', null, h('dt', null, k), h('dd', { class: mono ? 'mono' : '' }, v));
      const lbl = (list, code) => { const f = opts(list, []).find((x) => x.code === code); return f ? IDE.t(f.name) + ' (' + code + ')' : code; };
      const ct = cat();
      return h('div', { class: 'step' }, h('h2', null, 'Revisar e criar'),
        h('p', { class: 'help' }, 'Confira os dados. Ao confirmar, o ambiente é criado e o build começa imediatamente.'),
        h('div', { class: 'review-grid' },
          h('section', { class: 'rv' }, h('h3', null, 'Carro'), h('dl', { class: 'kv one' },
            row('Nome', W.name), row('iDrive', (genObj() || {}).name || '–'), row('Pasta da VM', W.home || IDE.t('pasta padrão do IDEmu'), true), row('Série', s.id + ' – ' + IDE.t(s.name)), row('Chassi', ch.code + ' – ' + ch.name), row('Marca', IDE.brandName(ch.brand)), row('VIN', c.vin, true))),
          h('section', { class: 'rv' }, h('h3', null, 'Codificação'), h('dl', { class: 'kv one' },
            row('Idioma', lbl(ct.languages, c.language)), row('País', lbl(ct.countries, c.country)),
            row('Unidades', (UNITS.find((u) => u[0] === c.units) || [0, c.units])[1]),
            row('Produção', String(c.month).padStart(2, '0') + '/' + c.year + ' · ' + (c.lci ? 'LCI' : IDE.t('Pré-LCI'))),
            row('Head unit', ((ct.hu_variants || []).find((v) => v.id === c.hu_variant) || { name: '–' }).name),
            row('Display', lbl(ct.displays, c.display)), row('HMI', lbl(ct.hmi_versions, c.hmi_version)), row('Navegação', lbl(ct.navi, c.navi)))),
          h('section', { class: 'rv' }, h('h3', null, 'Arquivos SWFL'), h('dl', { class: 'kv one' },
            roleList().map((r) => { const f = W.swfl[r.role]; return row(r.label, f ? f.file + (f.size ? ' · ' + IDE.fmtSize(f.size) : '') : IDE.t('não escolhido'), true); }))),
          h('section', { class: 'rv' }, h('h3', null, 'Rede'), h('dl', { class: 'kv one' },
            row('SSH', String(W.net.ssh_port), true), row('CAN', String(W.net.can_port), true), row('GPS', String(W.net.gps_port), true)))));
    }

    /* ---------------- criar + build ---------------- */
    function bodyFromState() {
      if (genObj() && genObj().direct) return { kind: genObj().direct, home: W.home || '', role: genObj().direct === 'mgu7' ? W.role : undefined,
        coding: genObj().direct === 'cic' ? Object.assign({ language: CIC_LANG[IDE.lang()] || 'en_GB' }, W.vin ? { vin: W.vin.vin } : {}) : W.vin ? { vin: W.vin.vin } : undefined, model_name: W.vin && W.vin.env ? [W.vin.chassis, W.vin.env.model_name].filter(Boolean).join(' ') : undefined, name: W.nameTouched && W.name.trim() ? W.name.trim() : genObj().name + (genObj().direct === 'mgu7' ? (W.role === 'rse' ? ' RSE' : ' CID') : genObj().direct === 'cic' ? '' : ' G70') };
      return {
        home: W.home || '', name: W.name.trim(), series: W.series, chassis: W.chassis, brand: brand(),
        swfl: Object.fromEntries(Object.keys(W.swfl).map((k) => [k, W.swfl[k].path])),
        coding: Object.assign({}, W.coding), net: Object.assign({}, W.net),
      };
    }
    async function createAndBuild() {
      W.phase = 'creating'; W.build = { state: 'none', pct: 0, step: 'Criando ambiente…', log: [] }; render();
      try {
        if (!W.env) W.env = await post('/api/env/create', bodyFromState());
      } catch (e) { toastErr(e); W.phase = 'edit'; render(); return; }
      await startBuild();
    }
    async function startBuild() {
      W.phase = 'building'; W.build = { state: 'building', pct: 0, step: 'Iniciando build…', log: [] }; render();
      try { await post('/api/env/' + W.env.id + '/build'); } catch (e) {
        toastErr(e); W.phase = 'builderr'; W.build.state = 'error'; W.build.error = e.message; render();
      }
    }
    function retryBuild() { startBuild(); }
    async function startNow(btn) {
      await IDE.busy(btn, async () => {
        try { await post('/api/env/' + W.env.id + '/start'); IDE.wizard.reset(); await IDE.refreshState().catch(() => {}); IDE.go('execucao'); } catch (e) { toastErr(e); }
      });
    }
    function monitorBuild() {
      if (stopBuildLoop) return;
      const id = W.env.id;
      stopBuildLoop = IDE.loop(async () => {
        const b = await api('/api/env/' + id + '/build');
        W.build = Object.assign({}, W.build, b);
        if (dead) return;
        if (b.state === 'ready') { W.phase = 'done'; stopBuild(); await IDE.refreshState().catch(() => {}); render(); toast('Build concluído.', 'success'); }
        else if (b.state === 'error') { W.phase = 'builderr'; stopBuild(); await IDE.refreshState().catch(() => {}); render(); }
        else updateBuildUI();
      }, 700);
    }
    function stopBuild() { if (stopBuildLoop) { stopBuildLoop(); stopBuildLoop = null; } }
    function buildPanel() {
      const b = W.build || {};
      const title = { creating: 'Criando ambiente…', building: 'Compilando ambiente…', done: 'Ambiente pronto!', builderr: 'O build falhou' }[W.phase];
      return h('div', { class: 'step build-panel' },
        h('h2', null, title),
        h('div', { class: 'build-prog big' },
          h('div', { class: 'bar' }, h('i', { id: 'wb-bar', class: W.phase === 'builderr' ? 'err' : (W.phase === 'done' ? 'ok' : ''), style: { width: (W.phase === 'done' ? 100 : (b.pct || 0)) + '%' } })),
          h('div', { class: 'prog-txt' }, h('span', { id: 'wb-step' }, b.step || ''), h('b', { id: 'wb-pct' }, (W.phase === 'done' ? 100 : (b.pct || 0)) + '%'))),
        W.phase === 'builderr' ? h('div', { class: 'note danger' }, ic('alert', 16), h('span', null, b.error || 'Erro desconhecido durante o build. Veja o log abaixo.')) : null,
        W.phase === 'done' ? h('div', { class: 'note ok' }, ic('check', 18), h('span', null, IDE.t('O ambiente "{name}" foi criado e compilado. Já pode iniciar.', { name: W.env ? W.env.name : '' }))) : null,
        h('div', { class: 'lbl' }, 'Log do build'),
        h('pre', { id: 'wb-log', class: 'logbox' }, (b.log || []).join('\n')));
    }
    function updateBuildUI() {
      const b = W.build || {};
      const bar = document.getElementById('wb-bar'); if (!bar) return;
      bar.style.width = (b.pct || 0) + '%';
      document.getElementById('wb-step').textContent = IDE.t(b.step || '');
      document.getElementById('wb-pct').textContent = (b.pct || 0) + '%';
      const lg = document.getElementById('wb-log');
      const atBottom = lg.scrollTop + lg.clientHeight >= lg.scrollHeight - 24;
      lg.textContent = (b.log || []).join('\n');
      if (atBottom) lg.scrollTop = lg.scrollHeight;
    }

    render();
    loadCat();
    return { unmount() { dead = true; stopBuild(); } };
  }
  IDE.views.wizard = { mount };
  IDE.wizard.reset();
})(window.IDE);
