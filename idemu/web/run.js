'use strict';
/* IDEmu – tela "Execução": display do carro, rotor iDrive em SVG, teclas, atalhos e abas. */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;
  const DISP_W = 1440, DISP_H = 540;
  const STEP_DEG = 18;           // graus de arraste por passo do rotor
  const KEYMAP = { m: 1, b: 2, o: 3, c: 4, r: 5, t: 6, n: 7 };
  const STATE_TXT = { stopped: ['Parado', 'muted'], booting: ['Iniciando', 'info'], running: ['Em execução', 'live'], error: ['Erro', 'danger'] };

  function sector(cx, cy, r1, r2, a1, a2) {
    const p = (r, a) => [(cx + r * Math.sin(a * Math.PI / 180)).toFixed(2), (cy - r * Math.cos(a * Math.PI / 180)).toFixed(2)];
    const [x1, y1] = p(r2, a1), [x2, y2] = p(r2, a2), [x3, y3] = p(r1, a2), [x4, y4] = p(r1, a1);
    return 'M' + x1 + ' ' + y1 + ' A' + r2 + ' ' + r2 + ' 0 0 1 ' + x2 + ' ' + y2 + ' L' + x3 + ' ' + y3 + ' A' + r1 + ' ' + r1 + ' 0 0 0 ' + x4 + ' ' + y4 + 'Z';
  }
  const CX = 150, CY = 190;     // centro do botão giratório no desenho do controle
  const HWBTNS = [  // [código, rótulo, x, y, largura, altura, dica]: o controle físico do iDrive 6/7 (MEDIA, COM, MENU, MAP, NAV, BACK, OPTION)
    [4, 'MEDIA', 16, -56, 74, 46, 'MEDIA (CD)'], [6, 'COM', 16, -2, 74, 46, 'COM (TEL)'], [1, 'MENU', 106, -72, 88, 112, 'MENU'],
    [5, 'MAP', 212, -56, 74, 46, 'MAP (RADIO)'], [7, 'NAV', 212, -2, 74, 46, 'NAV'], [2, 'BACK', 26, 316, 88, 34, 'BACK'], [3, 'OPTION', 186, 316, 88, 34, 'OPTION']];
  function rotorSVG() {
    let ticks = '';
    for (let i = 0; i < 120; i++) {
      const a = i * 3 * Math.PI / 180, big = i % 5 === 0, r1 = big ? 101 : 104, r2 = 112;
      const x1 = (CX + r1 * Math.sin(a)).toFixed(1), y1 = (CY - r1 * Math.cos(a)).toFixed(1), x2 = (CX + r2 * Math.sin(a)).toFixed(1), y2 = (CY - r2 * Math.cos(a)).toFixed(1);
      ticks += '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" stroke="' + (big ? 'rgba(0,0,0,.55)' : 'rgba(0,0,0,.32)') + '" stroke-width="' + (big ? 1.8 : 1.2) + '"/>';
    }
    const dirs = [['up', -45, 45], ['right', 45, 135], ['down', 135, 225], ['left', 225, 315]];
    let wedges = '';
    dirs.forEach(([d, a1, a2]) => {
      const mid = (a1 + a2) / 2 * Math.PI / 180, tx = CX + 66 * Math.sin(mid), ty = CY - 66 * Math.cos(mid), rot = (a1 + a2) / 2;
      wedges += '<g class="wedge" data-dir="' + d + '" role="button" tabindex="-1" aria-label="' + IDE.esc(IDE.t({ up: 'Inclinar para cima', down: 'Inclinar para baixo', left: 'Inclinar para a esquerda', right: 'Inclinar para a direita' }[d])) + '">' +
        '<path class="wp" d="' + sector(CX, CY, 42, 97, a1, a2) + '"/>' +
        '<path class="wa" d="M-8 4 L0 -4 L8 4" transform="translate(' + tx.toFixed(1) + ' ' + ty.toFixed(1) + ') rotate(' + rot + ')"/></g>';
    });
    let keys = '';
    HWBTNS.forEach(([code, label, x, y, w, hh, tip]) => {
      const menu = code === 1;
      keys += '<g class="hw" data-code="' + code + '" role="button" tabindex="-1"><title>' + IDE.esc(tip) + '</title>' +
        '<rect class="hwb" x="' + x + '" y="' + y + '" width="' + w + '" height="' + hh + '" rx="' + (menu ? 9 : 8) + '" fill="url(#hw-key)"/>' +
        (menu ? '<rect x="' + (x + 3) + '" y="' + (y + 4) + '" width="2.2" height="' + (hh - 8) + '" rx="1" fill="#9fe6d2" opacity=".55"/><rect x="' + (x + w - 5.2) + '" y="' + (y + 4) + '" width="2.2" height="' + (hh - 8) + '" rx="1" fill="#9fe6d2" opacity=".55"/>' : '') +
        '<text x="' + (x + w / 2) + '" y="' + (y + hh / 2 + 3.5) + '" text-anchor="middle" font-size="' + (menu ? 11 : 10) + '" font-weight="600" letter-spacing="1" fill="#d8dbe0" pointer-events="none">' + label + '</text></g>';
    });
    return '<svg class="rotor-svg" viewBox="-6 -86 312 452" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="' + IDE.esc(IDE.t('Rotor iDrive')) + '">' +
      '<defs>' +
      '<linearGradient id="hw-body" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#23252a"/><stop offset=".5" stop-color="#141518"/><stop offset="1" stop-color="#0b0c0e"/></linearGradient>' +
      '<linearGradient id="hw-key" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2c2f35"/><stop offset="1" stop-color="#15171a"/></linearGradient>' +
      '<linearGradient id="hw-chrome" gradientUnits="userSpaceOnUse" x1="50" y1="80" x2="250" y2="300"><stop offset="0" stop-color="#f6f7f9"/><stop offset=".18" stop-color="#8d9299"/><stop offset=".38" stop-color="#e9ebee"/><stop offset=".55" stop-color="#4b5058"/><stop offset=".75" stop-color="#d6d9de"/><stop offset="1" stop-color="#6b7078"/></linearGradient>' +
      '<linearGradient id="hw-rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff"/><stop offset=".5" stop-color="#555a61"/><stop offset="1" stop-color="#d9dce0"/></linearGradient>' +
      '<linearGradient id="hw-bevel" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stop-color="#eceef1"/><stop offset=".5" stop-color="#2a2c31"/><stop offset="1" stop-color="#9a9fa6"/></linearGradient>' +
      '<radialGradient id="hw-pad" cx="40%" cy="30%" r="80%"><stop offset="0" stop-color="#2a2c31"/><stop offset=".55" stop-color="#101114"/><stop offset="1" stop-color="#050506"/></radialGradient>' +
      '<linearGradient id="hw-sheen" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".16"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/></linearGradient>' +
      '</defs>' +
      '<path d="M18 -84 H282 Q300 -84 300 -66 V300 Q300 362 238 362 H62 Q0 362 0 300 V-66 Q0 -84 18 -84Z" fill="url(#hw-body)" stroke="#3a3d44" stroke-width="1.5"/>' +
      '<path d="M22 -80 H278" stroke="#fff" stroke-opacity=".12" stroke-width="1.5" stroke-linecap="round"/>' + keys +
      '<circle cx="' + CX + '" cy="' + CY + '" r="126" fill="#050506" stroke="#2b2d33" stroke-width="1.5"/>' +
      '<circle cx="' + CX + '" cy="' + CY + '" r="113" fill="url(#hw-chrome)"/>' +
      '<g id="rotor-ring" class="ring"><circle class="ring-hit" cx="' + CX + '" cy="' + CY + '" r="113" fill="rgba(0,0,0,0.01)"/>' + ticks + '</g>' +
      '<circle cx="' + CX + '" cy="' + CY + '" r="113" fill="none" stroke="url(#hw-rim)" stroke-width="2.5" pointer-events="none"/>' +
      '<circle cx="' + CX + '" cy="' + CY + '" r="104" fill="none" stroke="rgba(255,255,255,.25)" stroke-width=".8" pointer-events="none"/>' +
      '<circle cx="' + CX + '" cy="' + CY + '" r="100" fill="#000" stroke="url(#hw-bevel)" stroke-width="3"/>' +
      '<circle cx="' + CX + '" cy="' + CY + '" r="98" fill="url(#hw-pad)"/>' +
      wedges +
      '<g id="rotor-press" class="press" role="button" tabindex="-1" aria-label="' + IDE.esc(IDE.t('Pressionar (PRESS)')) + '"><circle cx="' + CX + '" cy="' + CY + '" r="40" fill="rgba(255,255,255,0)"/></g>' +
      '<path d="M' + (CX - 88) + ' ' + (CY - 30) + ' A92 92 0 0 1 ' + (CX + 40) + ' ' + (CY - 82) + ' Q' + (CX - 20) + ' ' + (CY - 50) + ' ' + (CX - 88) + ' ' + (CY - 30) + 'Z" fill="url(#hw-sheen)" pointer-events="none"/>' +
      '</svg>';
  }

  /* ====================================================================== view */
  function mount(root) {
    const R = { status: null, lastSeq: -1, haveImage: false, objUrl: null, tabs: {}, activeTab: null, ringAngle: 0, prevState: null, notified: false };
    const dead = () => R.dead;

    /* ---------- DOM ---------- */
    const barEnv = h('div', { class: 'rb-env' }), barState = h('span'), barUp = h('span', { class: 'rb-stat' }), barFps = h('span', { class: 'rb-stat' });
    const stopBtn = h('button', { class: 'btn danger-o', type: 'button' }, ic('stop', 16), 'Parar');
    const codingLink = h('a', { class: 'btn', href: '#/coding' }, ic('gear', 16), 'Coding');
    const statsLink = h('a', { class: 'btn', href: '#/estatisticas' }, ic('activity', 16), 'Estatísticas avançadas');
    const bar = h('div', { class: 'run-bar card' }, barEnv, barState, barUp, barFps, h('div', { class: 'spacer' }), statsLink, codingLink, stopBtn);
    const bootNote = h('span');
    const bootStep = h('span', { class: 'boot-step' }), bootPct = h('b'), bootBar = h('i'), bootEl = h('span', { class: 'muted small' });
    const boot = h('div', { class: 'boot card hidden' },
      h('div', { class: 'boot-top' }, h('div', { class: 'spinner' }), h('div', { class: 'boot-t' }, h('div', { class: 'boot-h' }, 'Iniciando o sistema do carro…'), bootStep), bootPct),
      h('div', { class: 'bar big' }, bootBar),
      h('div', { class: 'boot-foot muted small' }, bootNote, bootEl));
    const errBox = h('div', { class: 'note danger hidden' });

    const dispSize = h('span', { class: 'muted small' }, IDE.t('{w} × {h} · clique na tela para tocar', { w: DISP_W, h: DISP_H }));
    const img = h('canvas', { class: 'screen', width: DISP_W, height: DISP_H, role: 'img', 'aria-label': 'Display do carro' });
    img.style.display = 'none';
    const ripple = h('div', { class: 'ripple' });
    const ovIcon = h('div', { class: 'ov-ico' });
    const ovTxt = h('div', { class: 'ov-txt' }), ovSub = h('div', { class: 'ov-sub' });
    const ovBtn = h('a', { class: 'btn', href: '#/ambientes' }, 'Ir para Ambientes');
    const overlay = h('div', { class: 'overlay' }, ovIcon, ovTxt, ovSub, ovBtn);
    const dispWrap = h('div', { class: 'display-wrap', title: 'Clique para tocar na tela' }, img, overlay, ripple);
    const bezelImg = h('img', { class: 'bezel-photo', src: 'bezel.jpg', alt: '', draggable: 'false' });
    const bezelBox = h('div', { class: 'bmw-bezel' },
      bezelImg,
      h('div', { class: 'bezel-hole' }, dispWrap, h('div', { class: 'glare' })));
    // moldura (foto da central) ou só a imagem da tela; a escolha fica salva neste navegador
    const frameBtns = {};
    const frameSeg = h('div', { class: 'seg frame-seg', role: 'group', 'aria-label': 'Moldura da tela' },
      [['bezel', 'Moldura', 'Mostrar a foto da central multimídia em volta da tela'], ['plain', 'Só a tela', 'Mostrar só a imagem da tela, sem moldura']].map(([m, l, tip]) =>
        (frameBtns[m] = h('button', { type: 'button', class: 'segb', title: tip, onclick: () => setFrame(m) }, l))));
    function setFrame(m) {
      bezelBox.classList.toggle('plain', m === 'plain');
      Object.keys(frameBtns).forEach((k) => { frameBtns[k].classList.toggle('on', k === m); frameBtns[k].setAttribute('aria-pressed', String(k === m)); });
      IDE.pref.set('screenFrame', m);
    }
    const dispCard = h('div', { class: 'card display-card' },
      h('div', { class: 'card-title' }, h('span', null, 'Display do carro'), h('div', { class: 'disp-meta' }, dispSize, frameSeg)),
      bezelBox);
    setFrame(IDE.pref.get('screenFrame', 'bezel') === 'plain' ? 'plain' : 'bezel');

    // rotor + botões
    const rotorHost = h('div', { class: 'rotor-host', html: rotorSVG() });
    const svg = rotorHost.firstChild, ring = svg.querySelector('#rotor-ring');
    const btnEls = {};
    function wireKey(b) {
      const code = +b.dataset.code; btnEls[code] = b;
      const up = () => { if (b.classList.contains('active')) { b.classList.remove('active'); sendKey(code, 0); } };
      b.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; e.preventDefault(); b.setPointerCapture(e.pointerId); b.classList.add('active'); sendKey(code, 1); });
      b.addEventListener('pointerup', up); b.addEventListener('pointercancel', up);
    }
    const kbdTip = h('div', { class: 'kbd-tip' },
      h('div', { class: 'kt-title' }, ic('keyboard', 16), 'Atalhos de teclado'),
      h('ul', null,
        h('li', null, h('kbd', null, '←'), h('kbd', null, '→'), ' girar o rotor'),
        h('li', null, h('kbd', null, 'Enter'), ' / ', h('kbd', null, IDE.t('Espaço')), ' pressionar'),
        h('li', null, h('kbd', null, '↑'), h('kbd', null, '↓'), ' inclinar · ', h('kbd', null, 'Shift'), '+', h('kbd', null, '←'), h('kbd', null, '→'), ' inclinar lateral'),
        h('li', null, h('kbd', null, 'M'), h('kbd', null, 'B'), h('kbd', null, 'O'), h('kbd', null, 'C'), h('kbd', null, 'R'), h('kbd', null, 'T'), h('kbd', null, 'N'), ' teclas')),
      h('div', { class: 'muted small' }, 'Também: arraste o anel ou use a roda do mouse sobre o rotor.'));
    const ctrlCard = h('div', { class: 'card ctrl-card' },
      h('div', { class: 'card-title' }, h('span', null, 'Controlador iDrive')),
      h('div', { class: 'ctrl-body' }, rotorHost,
        h('div', { class: 'ctrl-side' }, kbdTip)));

    // abas
    const tabBar = h('div', { class: 'tabbar', role: 'tablist' });
    const tabBody = h('div', { class: 'tabbody' });
    const tabsCard = h('div', { class: 'card tabs-card' }, tabBar, tabBody);

    // tela "nenhum ambiente"
    const left = h('div', { class: 'run-left' }, dispCard, ctrlCard);
    const grid = h('div', { class: 'run-grid' }, left, tabsCard);
    root.appendChild(h('div', { class: 'page wide run-page' }, bar, boot, errBox, grid));

    /* ---------- entrada (fila serializada para manter a ordem) ---------- */
    let q = Promise.resolve();
    function send(path, body) {
      const st = R.status && R.status.state;
      if (st && st !== 'running') { toast(st === 'booting' ? 'Aguarde: o sistema ainda está iniciando.' : 'O emulador não está em execução.', 'info'); return; }
      q = q.then(() => api(path, { body }).catch((e) => { toastErr(e); }));
    }
    let rotorPend = 0, rotorT = null;
    function flushRotor() { clearTimeout(rotorT); rotorT = null; const d = rotorPend; rotorPend = 0; if (d) send('/api/input/rotor', { delta: d }); }
    const sendKey = (code, val) => { flushRotor(); send('/api/input/key', { code, val }); };
    svg.querySelectorAll('.hw').forEach(wireKey);
    const sendTilt = (dir) => { flushRotor(); send('/api/input/tilt', { dir }); };
    function sendRotor(n) {
      if (!n) return;
      rotorPend += n;
      if (rotorT) return;
      rotorT = setTimeout(flushRotor, 35);
    }
    function setRing(a) { R.ringAngle = a; ring.setAttribute('transform', 'rotate(' + a.toFixed(2) + ' ' + CX + ' ' + CY + ')'); }
    function nudgeRing(steps) {
      ring.style.transition = 'transform .12s ease-out'; setRing(R.ringAngle + steps * STEP_DEG);
      clearTimeout(nudgeRing.t); nudgeRing.t = setTimeout(() => { ring.style.transition = ''; }, 160);
    }
    function rotorStep(n) { nudgeRing(n); sendRotor(n); }
    function flashWedge(dir) {
      const w = svg.querySelector('.wedge[data-dir="' + dir + '"]'); if (!w) return;
      w.classList.add('on'); setTimeout(() => w.classList.remove('on'), 160);
    }
    function tilt(dir) { flashWedge(dir); sendTilt(dir); }
    let pressed = false;
    const pressEl = svg.querySelector('#rotor-press');
    function pressDown() { if (pressed) return; pressed = true; pressEl.classList.add('on'); sendKey(8, 1); }
    function pressUp() { if (!pressed) return; pressed = false; pressEl.classList.remove('on'); sendKey(8, 0); }

    // arraste do anel
    let drag = null;
    const ringEl = ring, ringHit = svg.querySelector('.ring-hit');
    function ang(e, c) { return Math.atan2(e.clientY - c.y, e.clientX - c.x) * 180 / Math.PI; }
    ringEl.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      const r = ringHit.getBoundingClientRect();
      const c = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
      drag = { c, last: ang(e, c), acc: 0 };
      ringEl.setPointerCapture(e.pointerId); ring.classList.add('grab'); ring.style.transition = '';
      e.preventDefault();
    });
    ringEl.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const a = ang(e, drag.c);
      let d = a - drag.last; if (d > 180) d -= 360; if (d < -180) d += 360;
      drag.last = a; drag.acc += d; setRing(R.ringAngle + d);
      const steps = Math.trunc(drag.acc / STEP_DEG);
      if (steps) { drag.acc -= steps * STEP_DEG; sendRotor(steps); }
    });
    const endDrag = () => { drag = null; ring.classList.remove('grab'); };
    ringEl.addEventListener('pointerup', endDrag); ringEl.addEventListener('pointercancel', endDrag);
    // roda do mouse
    let wheelAcc = 0;
    svg.addEventListener('wheel', (e) => {
      e.preventDefault();
      let dy = e.deltaY; if (e.deltaMode === 1) dy *= 16; else if (e.deltaMode === 2) dy *= 100;
      if (Math.abs(dy) >= 50) { rotorStep(dy > 0 ? 1 : -1); wheelAcc = 0; return; }
      wheelAcc += dy;
      if (Math.abs(wheelAcc) >= 40) { const s = Math.trunc(wheelAcc / 40); wheelAcc -= s * 40; rotorStep(s); }
    }, { passive: false });
    // centro e inclinações
    pressEl.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; pressEl.setPointerCapture(e.pointerId); pressDown(); e.preventDefault(); });
    pressEl.addEventListener('pointerup', pressUp); pressEl.addEventListener('pointercancel', pressUp);
    svg.querySelectorAll('.wedge').forEach((w) => {
      w.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; e.preventDefault(); tilt(w.dataset.dir); });
    });

    // clique no display
    function dispCoords(e) {
      const r = img.getBoundingClientRect();
      const W = img.width, H = img.height, x = Math.round((e.clientX - r.left) / r.width * W), y = Math.round((e.clientY - r.top) / r.height * H);
      return { x: Math.max(0, Math.min(W - 1, x)), y: Math.max(0, Math.min(H - 1, y)) };
    }
    let touch = null;
    dispWrap.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || !R.haveImage) return;
      const p = dispCoords(e); touch = p;
      dispWrap.setPointerCapture(e.pointerId); e.preventDefault();
      const wr = dispWrap.getBoundingClientRect();
      ripple.style.left = (e.clientX - wr.left) + 'px'; ripple.style.top = (e.clientY - wr.top) + 'px';
      ripple.classList.remove('go'); void ripple.offsetWidth; ripple.classList.add('go');
      flushRotor(); send('/api/input/click', { x: p.x, y: p.y, down: true });
    });
    const touchEnd = (e) => {
      if (!touch) return;
      const p = e.type === 'pointercancel' ? touch : dispCoords(e); touch = null;
      send('/api/input/click', { x: p.x, y: p.y, down: false });
    };
    dispWrap.addEventListener('pointerup', touchEnd); dispWrap.addEventListener('pointercancel', touchEnd);
    let lastMove = 0;
    dispWrap.addEventListener('pointermove', (e) => {       // arrastar: iDrive 5, 6 e 8
      if (!touch) return;
      const now = performance.now(); if (now - lastMove < 40) return; lastMove = now;
      const p = dispCoords(e); send('/api/input/click', { x: p.x, y: p.y, down: true, move: true });
    });

    /* ---------- teclado ---------- */
    const heldKeys = new Set();
    function onKeyDown(e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (IDE.isTyping(e.target) || document.querySelector('.backdrop')) return;
      // teclas num controle focado pelo teclado (abas, <summary> dos grupos do CAN, links) são dele, não do controlador iDrive
      const tgt = e.target, ctl = tgt && tgt !== document.body && tgt.matches && tgt.matches('button, a, summary, [role="tab"], [tabindex]:not([tabindex="-1"])');
      if (ctl && tgt.matches(':focus-visible') && tgt.closest('.tabs-card, .run-bar, .card-title')) return;     // depois de um clique com o mouse as setas continuam girando o rotor
      const k = e.key, onBtn = ctl && tgt.matches(':focus-visible');
      if (k === 'ArrowLeft' || k === 'ArrowRight') {
        e.preventDefault();
        if (e.shiftKey) tilt(k === 'ArrowLeft' ? 'left' : 'right'); else rotorStep(k === 'ArrowLeft' ? -1 : 1);
      } else if (k === 'ArrowUp' || k === 'ArrowDown') {
        e.preventDefault(); tilt(k === 'ArrowUp' ? 'up' : 'down');
      } else if (k === 'Enter' || k === ' ') {
        if (onBtn) return;
        e.preventDefault(); if (!e.repeat) { heldKeys.add(k); pressDown(); }
      } else if (KEYMAP[k.toLowerCase()] && !e.shiftKey) {
        e.preventDefault();
        const code = KEYMAP[k.toLowerCase()];
        if (!e.repeat) { heldKeys.add(k.toLowerCase()); btnEls[code].classList.add('active'); sendKey(code, 1); }
      }
    }
    function onKeyUp(e) {
      const k = e.key;
      if (k === 'Enter' || k === ' ') { if (heldKeys.delete(k)) { e.preventDefault(); pressUp(); } return; }
      const lk = k.toLowerCase();
      if (KEYMAP[lk] && heldKeys.delete(lk)) { const code = KEYMAP[lk]; btnEls[code].classList.remove('active'); sendKey(code, 0); }
    }
    document.addEventListener('keydown', onKeyDown); document.addEventListener('keyup', onKeyUp);
    const onBlur = () => { heldKeys.forEach((k) => { if (k === 'Enter' || k === ' ') pressUp(); else { const c = KEYMAP[k]; if (c) { btnEls[c].classList.remove('active'); sendKey(c, 0); } } }); heldKeys.clear(); };
    window.addEventListener('blur', onBlur);

    /* ---------- abas ---------- */
    const TABS = [['can', 'CAN', 'activity'], ['cluster', 'Cluster e HUD', 'gauge'], ['carplay', 'CarPlay', 'disc'], ['gps', 'GPS', 'pin'], ['map', 'Mapa', 'pin'], ['ssh', 'SSH', 'terminal'], ['phone', 'Celular', 'phone'], ['v850', 'V850', 'activity'], ['logs', 'Logs', 'file']];
    const ctx = { status: () => R.status, running: () => !!(R.status && R.status.state === 'running'), booted: () => !!(R.status && (R.status.state === 'running' || R.status.state === 'booting')) };
    function selectTab(id, persist = true) {
      if (R.activeTab && R.tabs[R.activeTab]) { R.tabs[R.activeTab].api.hide(); R.tabs[R.activeTab].host.hidden = true; }
      R.activeTab = id; if (persist) IDE.pref.set('run.tab', id);      // a troca forçada (CIC/iDrive 7/8 só têm Logs) não apaga a aba preferida
      let t = R.tabs[id];
      if (!t) { const host = h('div', { class: 'tab-host' }); tabBody.appendChild(host); t = R.tabs[id] = { host, api: IDE.tabDefs[id].mount(host, ctx) }; }
      t.host.hidden = false; t.api.show(); if (R.status && t.api.onStatus) t.api.onStatus(R.status);
      tabBar.querySelectorAll('button').forEach((b) => { const on = b.dataset.tab === id; b.classList.toggle('on', on); b.setAttribute('aria-selected', on); if (on) b.scrollIntoView({ block: 'nearest', inline: 'nearest' }); });
    }
    // a barra de abas rola na horizontal: a roda vertical do mouse também a rola
    tabBar.addEventListener('wheel', (e) => {
      if (tabBar.scrollWidth <= tabBar.clientWidth || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
      e.preventDefault(); tabBar.scrollBy({ left: e.deltaY, behavior: 'auto' });
    }, { passive: false });
    TABS.forEach(([id, label, icon]) => tabBar.appendChild(h('button', { class: 'tab', role: 'tab', type: 'button', 'data-tab': id, onclick: () => selectTab(id) }, ic(icon, 16), label)));
    selectTab(IDE.pref.get('run.tab', 'can') in IDE.tabDefs ? IDE.pref.get('run.tab', 'can') : 'can');

    /* ---------- parar ---------- */
    stopBtn.addEventListener('click', async () => {
      const env = R.status && R.status.env ? IDE.envById(R.status.env) : null;
      if (!await IDE.confirm({ title: 'Parar o emulador', message: env ? IDE.t('Parar "{name}"? O estado do sistema convidado será perdido.', { name: env.name }) : 'Parar o emulador? O estado do sistema convidado será perdido.', confirmLabel: 'Parar', danger: true, icon: 'stop' })) return;
      const id = (R.status && R.status.env) || IDE.state.running;
      await IDE.busy(stopBtn, async () => {
        try { await post('/api/env/' + id + '/stop'); toast('Emulador parado.', 'success'); await IDE.refreshState().catch(() => {}); IDE.go('ambientes'); } catch (e) { toastErr(e); }
      });
    });

    /* ---------- status & quadros ---------- */
    function setOverlay(kind, txt, sub) {
      overlay.className = 'overlay ' + kind;
      overlay.style.display = kind === 'none' ? 'none' : '';
      IDE.clear(ovIcon);
      if (kind === 'wait') ovIcon.appendChild(h('div', { class: 'spinner lg' }));
      else if (kind === 'off') ovIcon.appendChild(ic('power', 40));
      ovTxt.textContent = IDE.t(txt || ''); ovSub.textContent = IDE.t(sub || ''); ovBtn.hidden = kind !== 'off';
    }
    function applyStatus(s) {
      R.status = s;
      const envR = s.env ? IDE.envById(s.env) : null;
      const bz = s.kind === 'mgu22' ? 'id8' : s.kind === 'mgu7' ? ((s.role || (envR && envR.role)) === 'rse' ? 'rse' : 'id7') : s.kind === 'cic' ? 'cic' : 'id6';     // iDrive 7: tela central do Série 8 (G15); RSE só no ambiente do banco traseiro
      if (s.disp && s.disp[0] && !R.haveImage && dispWrap.dataset.disp !== String(s.disp)) {
        dispWrap.dataset.disp = String(s.disp); dispWrap.style.setProperty('--ar', String(s.disp[0] / s.disp[1]));
        dispSize.textContent = IDE.t('{w} × {h} · clique na tela para tocar', { w: s.disp[0], h: s.disp[1] });
      }
      if (bezelBox.dataset.k !== bz) { bezelBox.dataset.k = bz; bezelImg.src = { id8: 'bezel_id8.jpg', id7: 'bezel_id7.jpg', rse: 'bezel_rse.jpg', cic: 'bezel_cic.jpg', id6: 'bezel.jpg' }[bz]; }
      const mgu = !!s.kind;     // iDrive 8: sem CAN, GPS, mapa, SSH, V850 nem editor de codificação por enquanto
      codingLink.style.display = s.kind === 'cic' ? 'none' : '';
      if (s.kind === 'cic' && img.width) dispSize.textContent = IDE.t('{w} × {h} · sem tela de toque (use o controlador)', { w: img.width, h: img.height });      // o iDrive 7 tem o editor de codificação
      bootNote.textContent = IDE.t(s.kind === 'cic' ? 'O boot do CIC leva cerca de 1 minuto (emulação SH-4 sem aceleração).' : s.kind === 'mgu7' ? 'O primeiro boot do iDrive 7 leva cerca de 2 minutos (emulação x86 sem aceleração); os seguintes, cerca de 1 segundo.' : mgu ? 'O boot do iDrive 8 leva cerca de 1 minuto.' : 'O primeiro boot leva cerca de 45 segundos; os seguintes, cerca de 1 segundo.') + ' ';
      const carplayOk = !mgu && !!s.env && (s.state === 'running' || s.state === 'booting');      // CarPlay: só iDrive 5/6 (NBT Evo) em execução
      const shown = (t) => t === 'carplay' ? carplayOk : !mgu || t === 'logs' || t === 'phone' || (t === 'ssh' && (s.kind === 'cic' || s.kind === 'mgu7')) || (t === 'gps' && s.kind === 'cic');      // SSH: o CIC (ksh do QNX) e o iDrive 7 (shell do guest) têm console; GPS: o CIC tem um receptor ANTARIS virtual
      tabBar.querySelectorAll('button').forEach((b) => { b.style.display = shown(b.dataset.tab) ? '' : 'none'; });
      const want = IDE.pref.get('run.tab', 'can');      // a aba preferida volta quando reaparece (ex.: CarPlay durante o reinício da head unit)
      if (!shown(R.activeTab)) selectTab(mgu ? 'logs' : 'can', false);
      else if (R.activeTab !== want && want in IDE.tabDefs && shown(want)) selectTab(want, false);
      const env = s.env ? IDE.envById(s.env) : null;
      const envSig = env ? env.id + '|' + env.name + '|' + env.chassis : String(s.env);
      if (barEnv.dataset.sig !== envSig) {           // o status chega 4 vezes por segundo no boot: só refaz o cabeçalho quando o ambiente muda
        barEnv.dataset.sig = envSig; IDE.clear(barEnv);
        IDE.add(barEnv, ic('car', 20), h('span', null, env ? IDE.raw(env.name) : (s.env || 'Nenhum ambiente')), env ? h('span', { class: 'muted small' }, IDE.raw([env.chassis, IDE.brandName(env.brand)].join(' · '))) : null);
      }
      const [t, k] = STATE_TXT[s.state] || [s.state, 'muted'];
      barState.className = 'badge ' + k; barState.textContent = IDE.t(t);
      barUp.textContent = s.state === 'stopped' ? '' : IDE.t('Tempo ligado {t}', { t: IDE.fmtDur(s.uptime_s) });
      barFps.textContent = s.state === 'running' && s.fps != null ? IDE.t('{fps} quadros/s', { fps: IDE.fmtNum(s.fps, 1) }) : '';
      stopBtn.hidden = s.state === 'stopped';
      // boot
      const booting = s.state === 'booting';
      boot.classList.toggle('hidden', !booting);
      if (booting) {
        bootStep.textContent = IDE.t(s.boot_step || 'Iniciando…');
        const p = Math.max(0, Math.min(100, Number(s.boot_pct) || 0));
        bootBar.style.width = p + '%'; bootPct.textContent = p + '%';
        bootEl.textContent = IDE.t('Decorrido: {t}.', { t: IDE.fmtDur(s.uptime_s) });
      }
      if (s.error) { errBox.className = 'note danger'; IDE.clear(errBox); IDE.add(errBox, ic('alert', 16), h('span', null, s.error)); } else errBox.className = 'note danger hidden';
      grid.classList.toggle('inactive', s.state === 'stopped');
      // overlay do display
      if (s.state === 'stopped') { R.haveImage = false; img.style.display = 'none'; R.lastSeq = -1; setOverlay('off', 'Nenhum ambiente em execução', 'Inicie um ambiente na tela Ambientes.'); }
      else if (s.state === 'error' && !R.haveImage) setOverlay('off', 'O emulador encontrou um erro', s.error || 'Veja a aba Logs para detalhes.');
      else if (!R.haveImage) setOverlay('wait', 'Aguardando imagem…', booting ? 'O display aparece assim que o sistema desenhar o primeiro quadro.' : '');
      // quadro novo?
      if (R.prevState === 'booting' && s.state === 'running') toast(s.marks && s.marks.running != null ? IDE.t('Sistema pronto em {s} s.', { s: IDE.fmtNum(s.marks.running, 1) }) : 'Sistema pronto. O display está ativo.', 'success');
      R.prevState = s.state;
      TABS.forEach(([id]) => { const t = R.tabs[id]; if (t && t.api.onStatus) t.api.onStatus(s); });
    }
    /* quadros: pede sempre o próximo ao servidor (ele segura a resposta até haver um novo), sem acoplar a tela ao laço de status */
    /* WebGL: o quadro (RGB ou RGBA) vai direto para uma textura na GPU, sem laço por pixel em JavaScript. Sem WebGL, cai no canvas 2D. */
    function glPainter(cv) {
      let gl = null;
      try { gl = cv.getContext('webgl', { alpha: false, antialias: false, depth: false, stencil: false, desynchronized: true, powerPreference: 'low-power' }); } catch (e) { gl = null; }
      if (!gl) return null;
      let tex = null, tw = 0, th = 0, tf = 0, lost = false;
      function init() {
        const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
        const p = gl.createProgram();
        gl.attachShader(p, sh(gl.VERTEX_SHADER, 'attribute vec2 p;varying vec2 v;void main(){v=vec2(p.x+1.0,1.0-p.y)*0.5;gl_Position=vec4(p,0.0,1.0);}'));
        gl.attachShader(p, sh(gl.FRAGMENT_SHADER, 'precision mediump float;uniform sampler2D t;varying vec2 v;void main(){gl_FragColor=vec4(texture2D(t,v).rgb,1.0);}'));
        gl.linkProgram(p);
        if (!gl.getProgramParameter(p, gl.LINK_STATUS)) return false;
        gl.useProgram(p);
        gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
        const loc = gl.getAttribLocation(p, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
        tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, tex);
        [[gl.TEXTURE_MIN_FILTER, gl.NEAREST], [gl.TEXTURE_MAG_FILTER, gl.NEAREST], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]].forEach(([k, v]) => gl.texParameteri(gl.TEXTURE_2D, k, v));
        gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
        tw = th = tf = 0; return true;
      }
      cv.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost = true; });
      cv.addEventListener('webglcontextrestored', () => { lost = !init(); });
      if (!init()) return null;
      return function draw(px, w, hh, rgba) {
        if (lost) return;
        const f = rgba ? gl.RGBA : gl.RGB, data = new Uint8Array(px.buffer, px.byteOffset, w * hh * (rgba ? 4 : 3));
        if (w !== tw || hh !== th || f !== tf) { gl.texImage2D(gl.TEXTURE_2D, 0, f, w, hh, 0, f, gl.UNSIGNED_BYTE, data); tw = w; th = hh; tf = f; gl.viewport(0, 0, w, hh); }
        else gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, w, hh, f, gl.UNSIGNED_BYTE, data);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      };
    }
    const glDraw = glPainter(img);
    const ctx2d = glDraw ? null : img.getContext('2d', { alpha: false, desynchronized: true });
    let imgData = null;
    function paint(rgb, w, hh, rgba) {
      if (img.width !== w || img.height !== hh) {
        img.width = w; img.height = hh; imgData = null;
        dispWrap.style.aspectRatio = w + ' / ' + hh; dispWrap.style.setProperty('--ar', String(w / hh)); dispSize.textContent = R.status && R.status.kind === 'cic' ? IDE.t('{w} × {h} · sem tela de toque (use o controlador)', { w, h: hh }) : IDE.t('{w} × {h} · clique na tela para tocar', { w, h: hh });
      }
      if (glDraw) { glDraw(rgb, w, hh, rgba); return; }
      if (rgba) { ctx2d.putImageData(new ImageData(new Uint8ClampedArray(rgb.buffer, rgb.byteOffset, w * hh * 4), w, hh), 0, 0); return; }     // RGBA pronto: sem laço por pixel
      if (!imgData) { imgData = ctx2d.createImageData(w, hh); imgData.data.fill(255); }
      const o = imgData.data, n = w * hh;
      for (let i = 0, a = 0, c = 0; i < n; i++, a += 4, c += 3) { o[a] = rgb[c]; o[a + 1] = rgb[c + 1]; o[a + 2] = rgb[c + 2]; }
      ctx2d.putImageData(imgData, 0, 0);
    }
    async function frameLoop() {
      let since = -1;
      while (!dead()) {
        const st = R.status && R.status.state;
        if (st !== 'running' && st !== 'booting') { since = -1; await new Promise((r) => setTimeout(r, 200)); continue; }
        if (document.hidden) { await new Promise((r) => setTimeout(r, 500)); continue; }       // aba ou janela escondida: não puxa quadros de vários MB à toa
        try {
          const r = await fetch('/api/run/frame?fmt=rgba&since=' + since, { cache: 'no-store' });
          if (r.status === 200) {
            const seq = Number(r.headers.get('X-Frame-Seq')), w = Number(r.headers.get('X-Frame-W')), hh = Number(r.headers.get('X-Frame-H'));
            const buf = new Uint8Array(await r.arrayBuffer());
            if (dead()) return;
            paint(buf, w, hh, r.headers.get('X-Frame-Fmt') === 'rgba'); since = seq; R.lastSeq = seq;
            if (!R.haveImage) { R.haveImage = true; img.style.display = ''; setOverlay('none'); }
          } else if (r.status !== 204) await new Promise((res) => setTimeout(res, 300));
        } catch (e) { await new Promise((res) => setTimeout(res, 300)); }
      }
    }
    const stopLoop = IDE.loop(async () => {
      let s;
      try { s = await api('/api/run/status'); } catch (e) { return; }
      if (!dead()) applyStatus(s);
    }, () => (document.hidden ? 2000 : R.status && R.status.state === 'booting' ? 250 : R.status && R.status.state === 'running' ? 700 : 1000));
    setOverlay('wait', 'Conectando…');
    frameLoop();
    const offState = IDE.on('state', () => { if (R.status) applyStatus(R.status); });

    return {
      unmount() {
        R.dead = true; stopLoop(); offState();
        document.removeEventListener('keydown', onKeyDown); document.removeEventListener('keyup', onKeyUp); window.removeEventListener('blur', onBlur);
        TABS.forEach(([id]) => { const t = R.tabs[id]; if (t) { try { t.api.hide(); t.api.destroy && t.api.destroy(); } catch (e) { console.error(e); } } });
        onBlur();
      },
    };
  }
  IDE.views.run = { mount };
})(window.IDE);
