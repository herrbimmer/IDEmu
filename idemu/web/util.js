'use strict';
/* IDEmu – utilidades comuns: DOM, ícones, API, toasts, modais, preferências. Sem dependências. */
window.IDE = window.IDE || {};
(function (IDE) {
  /* ------------------------------------------------------------------ ícones (SVG inline) */
  const ICONS = {
    play: '<polygon points="7 4 20 12 7 20 7 4" fill="currentColor"/>',
    stop: '<rect x="5.5" y="5.5" width="13" height="13" rx="2" fill="currentColor"/>',
    palette: '<path d="M12 3a9 9 0 1 0 0 18c1 0 1.6-.8 1.6-1.6 0-.5-.2-.8-.5-1.2-.3-.3-.5-.7-.5-1.1 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5C21 6.4 17 3 12 3z"/><circle cx="7.5" cy="11" r="1" fill="currentColor"/><circle cx="10" cy="7.5" r="1" fill="currentColor"/><circle cx="14.5" cy="7.5" r="1" fill="currentColor"/>',
    wrench: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.1L3 17.7 6.3 21l6.3-6.3a4 4 0 0 0 5.1-5.4l-2.6 2.6-2.5-.5-.5-2.5z"/>',
    copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18h.01"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    car: '<path d="M4 16v-5l2-5h12l2 5v5M3 16h18v3H3zM7 13h.01M17 13h.01"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>',
    camera: '<path d="M4 8a2 2 0 0 1 2-2h2l1.5-2h5L16 6h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><circle cx="12" cy="12.5" r="3.5"/>',
    chevR: '<path d="M9 5l7 7-7 7"/>', chevL: '<path d="M15 5l-7 7 7 7"/>',
    chevU: '<path d="M5 15l7-7 7 7"/>', chevD: '<path d="M5 9l7 7 7-7"/>',
    arrowUp: '<path d="M12 19V6M6 11l6-6 6 6"/>',
    refresh: '<path d="M20 11a8 8 0 0 0-14.5-4M4 4v4h4M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4"/>',
    terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 10l3 2-3 2M13 15h4"/>',
    pin: '<path d="M12 21s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>',
    power: '<path d="M12 3v9M6.5 6.5a8 8 0 1 0 11 0"/>',
    pause: '<path d="M8 5v14M16 5v14" stroke-width="3"/>',
    record: '<circle cx="12" cy="12" r="6" fill="currentColor"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
    radio: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M7 8l10-5M8 14h.01M13 14h6"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A15 15 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
    nav: '<path d="M12 3l7 17-7-4-7 4z"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    gauge: '<path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-5"/>',
    back: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    option: '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    send: '<path d="M4 12l16-8-6 17-3-7z"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="2"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    minus: '<path d="M5 12h14"/>',
  };
  IDE.icon = function (name, size) {
    const s = size || 18;
    return '<svg class="ic" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (ICONS[name] || '') + '</svg>';
  };

  /* ------------------------------------------------------------------ DOM */
  const PROPS = new Set(['value', 'checked', 'disabled', 'selected', 'indeterminate', 'textContent', 'htmlFor', 'hidden']);
  const I18N_ATTRS = new Set(['title', 'aria-label', 'placeholder', 'alt']);
  const RAW_TAGS = new Set(['PRE', 'CODE', 'KBD']);
  /* Código, logs, VINs, nomes de arquivo e de parâmetro aparecem nestes elementos e não passam pelo tradutor: texto traduzível dentro deles usa IDE.t explicitamente. */
  const isRaw = (el) => RAW_TAGS.has(el.tagName) || (el.classList && el.classList.contains('mono'));
  function append(el, kids) {
    for (const k of kids) {
      if (k == null || k === false || k === true) continue;
      if (Array.isArray(k)) append(el, k);
      else if (k instanceof Node) el.appendChild(k);
      else if (typeof k === 'string' && !isRaw(el)) el.appendChild(document.createTextNode(IDE.t(k)));
      else el.appendChild(document.createTextNode(String(k)));
    }
  }
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k of Object.keys(attrs)) {
        const v = attrs[k];
        if (v == null || v === false && !PROPS.has(k)) continue;
        if (k === 'class') el.className = v;
        else if (k === 'style' && typeof v === 'object') for (const sk of Object.keys(v)) el.style.setProperty(sk, v[sk]);
        else if (k === 'style') el.setAttribute('style', v);
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') el.addEventListener(k.slice(2), v);
        else if (k === 'html') el.innerHTML = v;
        else if (k === 'for') el.htmlFor = v;
        else if (PROPS.has(k)) el[k] = v;
        else if (I18N_ATTRS.has(k) && typeof v === 'string') el.setAttribute(k, IDE.t(v));
        else el.setAttribute(k, v === true ? '' : v);
      }
    }
    append(el, kids);
    return el;
  }
  /** Elemento <span class="ico"> com um ícone SVG. */
  function ic(name, size) {
    const s = document.createElement('span');
    s.className = 'ico';
    s.innerHTML = IDE.icon(name, size);
    return s;
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
  function add(el, ...kids) { append(el, kids); return el; }
  /** Texto do usuário ou do sistema (nome de ambiente, chassi, arquivo): entra como está, sem passar pelo tradutor. */
  IDE.raw = (s) => document.createTextNode(s == null ? '' : String(s));
  Object.assign(IDE, { h, ic, clear, esc, add });

  /* ------------------------------------------------------------------ formatação */
  IDE.fmtSize = function (n) {
    if (n == null || isNaN(n)) return '–';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0, v = Number(n);
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return v.toLocaleString(IDE.locale(), { maximumFractionDigits: i === 0 ? 0 : (v >= 100 ? 0 : 1) }) + ' ' + u[i];
  };
  IDE.fmtDur = function (s) {
    s = Math.max(0, Math.floor(Number(s) || 0));
    const m = Math.floor(s / 60), ss = s % 60;
    if (m >= 60) return Math.floor(m / 60) + 'h ' + String(m % 60).padStart(2, '0') + 'min';
    return String(m).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
  };
  IDE.fmtDate = function (iso) {
    if (!iso) return '–';
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString(IDE.locale(), { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  };
  IDE.fmtNum = function (v, d) {
    if (v == null || isNaN(v)) return '–';
    return Number(v).toLocaleString(IDE.locale(), { maximumFractionDigits: d == null ? 2 : d });
  };
  /** Compara versões como 007_051_002. */
  IDE.verCmp = function (a, b) {
    const pa = String(a || '').split(/\D+/).filter(Boolean).map(Number);
    const pb = String(b || '').split(/\D+/).filter(Boolean).map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const d = (pa[i] || 0) - (pb[i] || 0);
      if (d) return d;
    }
    return 0;
  };
  IDE.baseName = (p) => String(p || '').split('/').filter(Boolean).pop() || '';

  /* ------------------------------------------------------------------ preferências de UI */
  IDE.pref = {
    get(k, d) {
      try { const v = localStorage.getItem('idemu.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; }
    },
    set(k, v) { try { localStorage.setItem('idemu.' + k, JSON.stringify(v)); } catch (e) { /* ignora */ } },
  };

  /* ------------------------------------------------------------------ eventos simples */
  const handlers = {};
  IDE.on = function (ev, fn) {
    (handlers[ev] = handlers[ev] || new Set()).add(fn);
    return () => handlers[ev].delete(fn);
  };
  IDE.emit = function (ev, data) { (handlers[ev] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); };

  /* ------------------------------------------------------------------ API */
  class ApiError extends Error {
    constructor(msg, status, net) { super(msg); this.status = status; this.net = !!net; }
  }
  IDE.ApiError = ApiError;
  let fails = 0;
  function markConn(ok) {
    if (ok) fails = 0; else fails++;
    const up = ok || fails < 2;
    if (IDE.conn !== up) { IDE.conn = up; IDE.emit('conn', up); }
  }
  IDE.conn = true;
  /** api(url, {body, method, signal}) -> JSON. Lança ApiError (net=true se o servidor não respondeu). */
  IDE.api = async function (url, opts) {
    opts = opts || {};
    const init = { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), cache: 'no-store', headers: {} };
    if (opts.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    if (opts.signal) init.signal = opts.signal;
    let r;
    try { r = await fetch(url, init); } catch (e) {
      if (e && e.name === 'AbortError') throw e;
      markConn(false);
      throw new ApiError(IDE.t('Sem conexão com o servidor do IDEmu.'), 0, true);
    }
    markConn(true);
    let data = null;
    const txt = await r.text();
    try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
    if (!r.ok) throw new ApiError(data && data.error ? IDE.t(data.error) : IDE.t('Erro {status} do servidor.', { status: r.status }), r.status);
    return data;
  };
  IDE.post = (url, body) => IDE.api(url, { body: body === undefined ? {} : body });
  IDE.qs = (o) => Object.keys(o).filter((k) => o[k] != null).map((k) => encodeURIComponent(k) + '=' + encodeURIComponent(o[k])).join('&');

  /* ------------------------------------------------------------------ toasts */
  const recent = new Map();
  IDE.toast = function (msg, type, ms) {
    type = type || 'info';
    msg = IDE.t(msg);
    const root = document.getElementById('toasts');
    if (!root) return;
    const key = type + '|' + msg;
    const now = Date.now();
    if (recent.has(key) && now - recent.get(key) < 2500) return; // evita repetição em rajada
    recent.set(key, now);
    const icon = { success: 'check', error: 'alert', info: 'info', warn: 'alert' }[type] || 'info';
    const el = h('div', { class: 'toast ' + type, role: type === 'error' ? 'alert' : 'status' },
      ic(icon, 18), h('div', { class: 'msg' }, msg),
      h('button', { class: 'x', title: 'Fechar', 'aria-label': 'Fechar', onclick: () => kill() }, ic('x', 14)));
    root.appendChild(el);
    requestAnimationFrame(() => el.classList.add('in'));
    let t = setTimeout(kill, ms || (type === 'error' ? 7000 : 4200));
    function kill() { clearTimeout(t); el.classList.remove('in'); setTimeout(() => el.remove(), 250); }
    while (root.children.length > 5) root.firstChild.remove();
  };
  IDE.toastErr = function (e) {
    if (e && e.name === 'AbortError') return;
    IDE.toast((e && e.message) || 'Erro inesperado.', 'error');
  };

  /* ------------------------------------------------------------------ modais */
  const openModals = new Set();
  /* fecha todos os diálogos pelo close() de cada um (onClose roda, o listener de teclado sai): a troca de tela usava IDE.clear e deixava os dois para trás */
  IDE.closeModals = function () { Array.from(openModals).forEach((m) => { try { m.close(); } catch (e) { console.error(e); } }); };
  IDE.modal = function (opts) {
    const root = document.getElementById('modal-root');
    const locked = !!opts.locked;         // locked: sem X, sem Esc e sem clique fora (operação em andamento no servidor); persistent: só sem clique fora
    const prevFocus = document.activeElement;
    const body = h('div', { class: 'modal-body' });
    const foot = h('div', { class: 'modal-foot' });
    const titleEl = h('h2', null, opts.title || '');
    const box = h('div', { class: 'modal ' + (opts.size || ''), role: 'dialog', 'aria-modal': 'true', 'aria-label': opts.title || 'Diálogo' },
      h('div', { class: 'modal-head' }, titleEl,
        locked ? null : h('button', { class: 'icon-btn', title: 'Fechar', 'aria-label': 'Fechar', onclick: () => api.close() }, ic('x', 18))),
      body, foot);
    const back = h('div', { class: 'backdrop' }, box);
    let closed = false;
    const api = {
      el: box, body, foot, setTitle(t) { titleEl.textContent = IDE.t(t); },
      close(val) {
        if (closed) return; closed = true; openModals.delete(api);
        document.removeEventListener('keydown', onKey, true);
        back.classList.remove('in');
        setTimeout(() => back.remove(), 180);
        if (prevFocus && prevFocus.focus) setTimeout(() => { try { prevFocus.focus(); } catch (e) { /* */ } }, 0);
        if (opts.onClose) opts.onClose(val);
      },
    };
    function onKey(e) {
      if (root.lastElementChild !== back) return; // só o diálogo do topo reage
      if (e.key === 'Escape') { e.stopPropagation(); if (!locked) api.close(); }
      else if (e.key === 'Tab') { // prende o foco no diálogo
        const f = box.querySelectorAll('button:not([disabled]),input:not([disabled]),select,textarea,[tabindex="0"]');
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    }
    back.addEventListener('mousedown', (e) => { if (e.target === back && !opts.persistent && !locked) api.close(); });
    document.addEventListener('keydown', onKey, true); openModals.add(api);
    if (opts.body) append(body, [opts.body]);
    (opts.actions || []).forEach((a) => {
      const b = h('button', { class: 'btn ' + (a.kind || ''), type: 'button' }, a.icon ? ic(a.icon, 16) : null, a.label);
      b.addEventListener('click', async () => {
        if (a.onClick) { const r = await a.onClick(api, b); if (r === false) return; }
        if (a.closes !== false) api.close(a.value);
      });
      foot.appendChild(b);
    });
    if (!opts.actions || !opts.actions.length) foot.remove();
    root.appendChild(back);
    requestAnimationFrame(() => back.classList.add('in'));
    setTimeout(() => {
      const f = box.querySelector('[data-autofocus]') || box.querySelector('.btn.primary,.btn.danger,input,button');
      if (f && f.focus) f.focus();
    }, 30);
    return api;
  };
  IDE.confirm = function (o) {
    return new Promise((resolve) => {
      let res = false;
      IDE.modal({
        title: o.title || 'Confirmar', size: 'sm',
        body: h('p', { class: 'confirm-msg' }, o.message),
        actions: [
          { label: o.cancelLabel || 'Cancelar', value: false },
          { label: o.confirmLabel || 'Confirmar', kind: o.danger ? 'danger' : 'primary', icon: o.icon, onClick: () => { res = true; } },
        ],
        onClose: () => resolve(res),
      });
    });
  };
  IDE.prompt = function (o) {
    return new Promise((resolve) => {
      let res = null;
      const input = h('input', { type: 'text', class: 'input', value: o.value || '', 'data-autofocus': '', maxlength: o.maxlength || 60, placeholder: o.placeholder || '' });
      const submit = (api) => { const v = input.value.trim(); if (!v) { input.focus(); return false; } res = v; api.close(); };
      const m = IDE.modal({
        title: o.title, size: 'sm',
        body: h('div', null, o.message ? h('p', { class: 'confirm-msg' }, o.message) : null, input),
        actions: [{ label: 'Cancelar' }, { label: o.confirmLabel || 'OK', kind: 'primary', closes: false, onClick: (api) => submit(api) }],
        onClose: () => resolve(res),
      });
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); submit(m); } });
      setTimeout(() => input.select(), 40);
    });
  };

  /* ------------------------------------------------------------------ helpers de UI */
  /** Desabilita o botão enquanto a promessa roda. */
  IDE.busy = async function (btn, fn) {
    if (btn) { btn.disabled = true; btn.classList.add('busy'); }
    try { return await fn(); } finally { if (btn) { btn.disabled = false; btn.classList.remove('busy'); } }
  };
  IDE.copyText = async function (text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* tenta o método antigo */ }
    try {
      const ta = h('textarea', { style: { position: 'fixed', opacity: '0', top: '0' } }); ta.value = text;
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand('copy'); ta.remove(); return ok;
    } catch (e) { return false; }
  };
  IDE.badge = (text, kind) => h('span', { class: 'badge ' + (kind || '') }, text);
  IDE.isTyping = function (t) {
    if (!t) return false;
    const tag = (t.tagName || '').toUpperCase();
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t.isContentEditable;
  };
  /** Cria um intervalo que se auto-cancela via retorno. */
  IDE.every = function (fn, ms) { const id = setInterval(fn, ms); return () => clearInterval(id); };
  /** Laço assíncrono com setTimeout (evita sobreposição de requisições). Retorna função de parada. */
  IDE.loop = function (fn, msFn) {
    let stop = false, t = null;
    async function run() {
      if (stop) return;
      try { await fn(); } catch (e) { /* silencioso: reconecta sozinho */ }
      if (stop) return;
      const ms = typeof msFn === 'function' ? msFn() : msFn;
      t = setTimeout(run, document.hidden ? Math.max(ms, 3000) : ms);      // janela ou aba escondida: no máximo uma consulta a cada 3 s
    }
    run();
    return () => { stop = true; clearTimeout(t); };
  };
  IDE.views = {};
})(window.IDE);
