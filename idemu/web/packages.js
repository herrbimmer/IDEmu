'use strict';
/* IDEmu – arquivos do sistema (SWFL) do CIC, iDrive 7 e 8: lista com os nomes exigidos, escolha um a um, vários de uma vez, ou busca numa pasta.
   IDE.pkgPanel(kind, {onChange(status)}) -> elemento (com .status e .reload()); IDE.filesSetup() -> painel completo com a escolha da geração. */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;
  const KINDS = [['cic', 'CIC'], ['mgu7', 'iDrive 7'], ['mgu22', 'iDrive 8']];

  async function pickNative(kind, prompt, start) {
    if (window.idemuNative) { try { return { native: true, r: await window.idemuNative.pick(kind, prompt, start) }; } catch (e) { /* cai no seletor do servidor */ } }
    try { const r = await post('/api/pick', { kind, prompt, start }); return { native: true, r }; } catch (e) { return { native: false }; }
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); toast(IDE.t('Nome copiado: {name}', { name: t }), 'success'); }
    catch (e) {
      const ta = h('textarea', { style: { position: 'fixed', opacity: '0' } }, t); document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); toast(IDE.t('Nome copiado: {name}', { name: t }), 'success'); } catch (e2) { toast(IDE.t('Não consegui copiar.'), 'error'); }
      ta.remove();
    }
  }

  IDE.pkgPanel = function (kind, o) {
    o = o || {};
    const root = h('div', { class: 'pkg-panel' });
    let st = null, busy = false, last = null;
    const isMgu22 = kind === 'mgu22';
    const setSt = (s) => { st = s; root.status = s; if (o.onChange) o.onChange(s); render(); };
    async function reload() { try { setSt(await api('/api/packages?' + IDE.qs({ kind }))); } catch (e) { toastErr(e); } }
    async function run(fn) { busy = true; render(); try { await fn(); } catch (e) { toastErr(e); } busy = false; render(); }

    function report(res, before) {
      const bad = (res.results || []).filter((x) => !x.ok);
      const nowHave = res.have - before;
      if (bad.length) toast(IDE.t('{n} arquivo(s) não servem: {why}', { n: bad.length, why: IDE.t(bad[0].message) }), 'error');
      if (nowHave > 0) toast(IDE.t('{n} arquivo(s) encontrados.', { n: nowHave }), 'success');
      else if (!bad.length) toast(IDE.t('Nenhum arquivo novo encontrado.'), 'info');
    }
    const startDir = () => (last && last.scan) || IDE.state.settings.psdz_path || undefined;
    async function scan() {
      const n = await pickNative('folder', IDE.t(isMgu22 ? 'Escolher a pasta com os arquivos' : 'Escolha uma pasta que contenha os arquivos swfl_… (ela e as subpastas são varridas)'), startDir());
      let path = n.native ? n.r.path : null;
      if (!n.native) { const r = await IDE.pickPath({ mode: 'dir', start: startDir(), title: IDE.t('Escolher a pasta com os arquivos') }); path = r && r.path; }
      if (!path) return;
      await run(async () => {
        const before = st ? st.have : 0;
        const r = await post('/api/packages/scan', { kind, path });
        last = { scan: r.scanned_path }; if (r.timeout) toast(IDE.t('(a busca foi interrompida por demorar demais)'), 'info');
        report(r, before); setSt(r);
      });
    }
    async function pickMany() {
      const n = await pickNative('files', IDE.t(isMgu22 ? 'Escolher vários arquivos…' : 'Selecione os arquivos swfl_… (use ⌘ ou Shift para vários)'), startDir());
      let paths = [];
      if (n.native) paths = n.r.paths || [];
      else { const r = await IDE.pickPath({ mode: 'file', start: startDir(), title: IDE.t('Escolher arquivo'), hint: isMgu22 ? 'swfl_*.bin.* / swfk_*.bin.*' : 'swfl_*.bin.*' }); paths = r ? [r.path] : []; }
      await sendPaths(paths);
    }
    async function pickOne(it) {
      const n = await pickNative('file', IDE.t('Escolha o arquivo {name}', { name: it.file }), startDir());
      let path = n.native ? n.r.path : null;
      if (!n.native) { const r = await IDE.pickPath({ mode: 'file', start: startDir(), title: IDE.t('Escolher arquivo'), hint: it.file }); path = r && r.path; }
      if (path) await sendPaths([path]);
    }
    async function sendPaths(paths) {
      if (!paths.length) return;
      await run(async () => {
        const before = st ? st.have : 0;
        const r = await post('/api/packages/pick', { kind, paths });
        last = { scan: paths[0].replace(/\/[^/]*$/, '') || '/' };
        report(r, before); setSt(r);
      });
    }

    function row(it) {
      return h('div', { class: 'need ' + (it.found ? 'ok' : 'missing') },
        h('div', { class: 'role-ico' }, ic(it.found ? 'check' : 'file', 20)),
        h('div', { class: 'nd' },
          h('h3', null, IDE.t(it.label)),
          h('div', { class: 'fname' }, it.file),
          it.found ? h('div', { class: 'got' }, ic('check', 14), h('span', { class: 'mono' }, IDE.fmtSize(it.size) + (it.source === 'escolhido' ? ' · ' + IDE.t('escolhido por você') : ''))) : null,
          it.found ? h('div', { class: 'why mono' }, it.path)
            : (it.other && it.other.length ? h('div', { class: 'note warn' }, ic('alert', 16), h('span', null, IDE.t('Achei outra versão ({name}), mas o IDEmu precisa da {ver}.', { name: it.other[0], ver: it.version }))) : h('div', { class: 'why' }, IDE.t(it.help)))),
        h('div', { class: 'vers' },
          h('button', { class: 'btn', type: 'button', title: IDE.t('Copia o nome para colar na busca do Finder'), onclick: () => copyText(it.file) }, ic('copy', 16), IDE.t('Copiar nome')),
          h('button', { class: 'btn' + (it.found ? '' : ' primary-o'), type: 'button', disabled: busy, onclick: () => pickOne(it) }, ic('file', 16), it.found ? IDE.t('Trocar…') : IDE.t('Escolher…'))));
    }

    function render() {
      IDE.clear(root);
      if (!st) { root.appendChild(h('div', { class: 'loading' }, IDE.t('Carregando…'))); return; }
      const ok = st.ok;
      root.appendChild(h('div', { class: 'need-banner' + (ok ? ' ok' : '') },
        h('div', { class: 'ico-big' }, ic(ok ? 'check' : 'folder', 22)),
        h('div', { class: 'nb-t' }, h('b', null, ok ? IDE.t('Tudo certo: {n} de {total} arquivos', { n: st.have, total: st.total }) : IDE.t('{n} de {total} arquivos encontrados', { n: st.have, total: st.total })),
          h('span', null, last && last.scan ? IDE.t('Última pasta: {path}', { path: last.scan }) : IDE.t('Copie o nome, procure no Finder e escolha o arquivo, ou deixe o app procurar numa pasta.'))),
        h('div', { class: 'pkg-actions' },
          h('button', { class: 'btn primary', type: 'button', disabled: busy, onclick: scan }, ic('folder', 16), busy ? IDE.t('Procurando…') : IDE.t('Procurar numa pasta…')),
          h('button', { class: 'btn', type: 'button', disabled: busy, onclick: pickMany }, ic('file', 16), IDE.t('Escolher vários arquivos…')))));
      root.appendChild(h('div', { class: 'need-list' }, st.items.slice().sort((a, b) => (a.found - b.found)).map(row)));
    }
    root.reload = reload; render(); reload();
    return root;
  };

  /** Painel completo: escolhe a geração (ou a pasta PSdZData do iDrive 5/6) e mostra os arquivos. */
  IDE.filesSetup = function (o) {
    o = o || {};
    const holder = h('div'); let tab = IDE.pref.get('files.tab', 'cic');
    const tabs = h('div', { class: 'fs-tabs' });
    function render() {
      IDE.clear(tabs); IDE.clear(holder);
      KINDS.concat([['psdz', 'iDrive 5/6 (PSdZData)']]).forEach(([id, label]) => tabs.appendChild(h('button', { type: 'button', class: 'fs-tab' + (tab === id ? ' on' : ''), onclick: () => { tab = id; IDE.pref.set('files.tab', id); render(); } }, label)));
      if (tab === 'psdz') holder.appendChild(IDE.psdzForm({ onSaved: o.onSaved }));
      else holder.appendChild(IDE.pkgPanel(tab, { onChange: o.onChange }));
    }
    render();
    return h('div', { class: 'files-setup' }, tabs, holder);
  };
})(window.IDE);
