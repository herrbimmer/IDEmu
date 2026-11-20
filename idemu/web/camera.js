'use strict';
/* IDEmu – câmera de ré virtual: usa a webcam do computador (getUserMedia) e a mostra sobre o display do carro quando a marcha
   ré está engatada no CAN virtual (gear_position = 1), com as linhas-guia de estacionamento (fixas ou seguindo o volante).
   Tudo acontece no navegador/Electron: nenhum quadro de vídeo vai ao servidor nem ao sistema convidado. A webcam só fica ligada
   enquanto a imagem está sendo mostrada (ou a aba "Câmera" aberta), então a luz da câmera não fica acesa à toa. */
(function (IDE) {
  const { h, ic, api, post, toast, toastErr } = IDE;
  const GEAR_R = 1;                      // mesmo valor do cluster.js: 0 P, 1 R, 2 N, 3 D
  const RELEASE_MS = 1500;               // desliga a webcam pouco depois de sair da ré (evita piscar ao engatar R-N-R)
  const MODES = ['auto', 'on', 'off'], GUIDES = ['off', 'static', 'dynamic'];

  const pick = (key, list, dflt) => { const v = IDE.pref.get(key, dflt); return list.indexOf(v) >= 0 ? v : dflt; };
  const S = {
    mode: pick('rvc.mode', MODES, 'auto'), guides: pick('rvc.guides', GUIDES, 'dynamic'),
    mirror: IDE.pref.get('rvc.mirror', false) === true, device: String(IDE.pref.get('rvc.device', '') || ''),
    stream: null, state: 'off', err: '', gear: 0, steer: 0, reverse: false, owners: new Set(), seq: 0, releaseT: null, devices: [],
  };

  /* ------------------------------------------------------------------ webcam */
  function setState(st, err) {
    if (S.state === st && S.err === (err || '')) return;
    S.state = st; S.err = err || ''; IDE.emit('rvc', S);
  }
  function errText(e) {
    const n = e && e.name;
    if (n === 'NotAllowedError' || n === 'SecurityError') return 'Sem permissão para usar a webcam. Libere o acesso à câmera nas configurações do sistema ou do navegador.';
    if (n === 'NotFoundError' || n === 'OverconstrainedError') return 'Nenhuma webcam encontrada.';
    if (n === 'NotReadableError' || n === 'AbortError') return 'A webcam está em uso por outro aplicativo.';
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'Este navegador não permite acessar a webcam (use http://127.0.0.1 ou localhost).';
    return 'Não foi possível abrir a webcam.';
  }
  async function listDevices() {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
      S.devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
      IDE.emit('rvc', S);
    } catch (e) { /* sem lista */ }
  }
  async function openStream() {
    const my = ++S.seq;
    setState('starting');
    const base = { width: { ideal: 1280 }, height: { ideal: 720 } };
    let st = null, last = null;
    for (const v of (S.device ? [Object.assign({ deviceId: { exact: S.device } }, base), base] : [base])) {       // webcam salva sumiu (USB desligada)? cai na padrão
      try { st = await navigator.mediaDevices.getUserMedia({ video: v, audio: false }); break; } catch (e) { last = e; }
    }
    if (my !== S.seq || !S.owners.size) { if (st) st.getTracks().forEach((t) => t.stop()); return; }       // ninguém mais quer a imagem
    if (!st) { setState('error', errText(last)); return; }
    S.stream = st;
    st.getVideoTracks().forEach((t) => t.addEventListener('ended', () => { if (S.stream === st) { S.stream = null; setState('error', 'A webcam foi desconectada.'); } }));
    setState('live');
    listDevices();                      // os nomes só aparecem depois da permissão
  }
  function closeStream() {
    S.seq++; clearTimeout(S.releaseT); S.releaseT = null;
    if (S.stream) { S.stream.getTracks().forEach((t) => t.stop()); S.stream = null; }
    setState('off');
  }
  function acquire(who) {
    S.owners.add(who); clearTimeout(S.releaseT); S.releaseT = null;
    if (!S.stream && S.state !== 'starting') {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { setState('error', errText(null)); return; }
      openStream();
    }
  }
  function release(who) {
    S.owners.delete(who);
    if (S.owners.size || (!S.stream && S.state !== 'starting')) return;
    clearTimeout(S.releaseT); S.releaseT = setTimeout(() => { if (!S.owners.size) closeStream(); }, RELEASE_MS);
  }
  function restart() { if (S.owners.size) { closeStream(); const o = new Set(S.owners); S.owners.clear(); o.forEach(acquire); } }

  /* ------------------------------------------------------------------ linhas-guia */
  // Faixa de chão em perspectiva: cantos na base, ponto de fuga acima do centro. O volante (-720..720°) curva a trajetória.
  function drawGuides(cv, steer) {
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const w = Math.max(2, Math.round(r.width * dpr)), hh = Math.max(2, Math.round(r.height * dpr));
    if (cv.width !== w || cv.height !== hh) { cv.width = w; cv.height = hh; }
    const g = cv.getContext('2d'); g.clearRect(0, 0, w, hh);
    if (S.guides === 'off') return;
    const bend = S.guides === 'dynamic' ? Math.max(-1, Math.min(1, steer / 540)) : 0;
    const yFar = hh * 0.52, yNear = hh * 0.97, cx = w / 2;
    const halfNear = w * 0.36, halfFar = w * 0.13, shift = bend * w * 0.26;
    const pt = (t, side) => {                        // t: 0 = perto (base), 1 = longe
      const y = yNear + (yFar - yNear) * t, half = halfNear + (halfFar - halfNear) * t;
      return [cx + side * half + shift * t * t, y];
    };
    const color = (t) => (t < 0.34 ? '#ff4d3d' : t < 0.68 ? '#ffc933' : '#37d67a');
    g.lineCap = 'round'; g.lineWidth = Math.max(3, w * 0.008);
    const N = 36;
    for (const side of [-1, 1]) {
      for (let i = 0; i < N; i++) {
        const t0 = i / N, t1 = (i + 1) / N, a = pt(t0, side), b = pt(t1, side);
        g.strokeStyle = color((t0 + t1) / 2); g.globalAlpha = 0.95 - 0.35 * t0;
        g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
      }
    }
    for (const t of [0.34, 0.68, 1]) {                // travessas de distância
      const a = pt(t, -1), b = pt(t, 1);
      g.strokeStyle = color(t - 0.01); g.globalAlpha = 0.9; g.beginPath(); g.moveTo(a[0], a[1]); g.lineTo(b[0], b[1]); g.stroke();
    }
    g.globalAlpha = 1;
  }

  /* ------------------------------------------------------------------ overlay sobre o display */
  function attach(dispWrap) {
    const video = h('video', { class: 'rvc-video', autoplay: '', muted: '', playsinline: '' });
    video.muted = true;
    const cv = h('canvas', { class: 'rvc-guides' });
    const msg = h('div', { class: 'rvc-msg' });
    const tag = h('div', { class: 'rvc-tag' }, 'R');
    const box = h('div', { class: 'rvc', 'aria-hidden': 'true' }, video, cv, tag, msg);
    dispWrap.appendChild(box);
    let shown = false, raf = 0, stopPoll = null, dead = false;
    const OWNER = 'overlay';

    function want() { return S.mode === 'on' || (S.mode === 'auto' && S.reverse); }
    function paint() {
      box.classList.toggle('on', shown);
      video.classList.toggle('mirror', S.mirror);
      if (S.stream && video.srcObject !== S.stream) { video.srcObject = S.stream; const p = video.play(); if (p && p.catch) p.catch(() => {}); }
      if (!S.stream && video.srcObject) video.srcObject = null;
      msg.textContent = shown && S.state !== 'live' ? IDE.t(S.state === 'error' ? S.err : 'Abrindo a webcam…') : '';
      msg.classList.toggle('err', S.state === 'error');
    }
    function sync() {
      if (dead) return;
      const w = want();
      if (w && !shown) { shown = true; acquire(OWNER); if (!raf) tick(); }
      else if (!w && shown) { shown = false; release(OWNER); }
      paint();
    }
    function tick() {
      if (dead || !shown) { raf = 0; return; }
      drawGuides(cv, S.steer); raf = requestAnimationFrame(tick);
    }
    const off = IDE.on('rvc', sync);
    async function poll() {
      let rev = false;
      try {
        const d = await api('/api/cluster'), v = (d && d.signals) || {};
        S.gear = Math.round(v.gear_position || 0); S.steer = Number(v.steering_angle) || 0; rev = S.gear === GEAR_R;
      } catch (e) { rev = false; }          // ambiente parado ou sem CAN: sem ré
      if (rev !== S.reverse) { S.reverse = rev; IDE.emit('rvc', S); }
      sync();
    }
    stopPoll = IDE.loop(poll, 350);
    sync();
    return function detach() {
      dead = true; off(); if (stopPoll) stopPoll(); cancelAnimationFrame(raf);
      if (shown) release(OWNER);
      box.remove();
    };
  }

  /* ------------------------------------------------------------------ aba "Câmera" */
  IDE.tabDefs.camera = {
    mount(host) {
      const OWNER = 'tab';
      const seg = (key, opts, cur, onPick) => {
        const btns = {};
        const el = h('div', { class: 'seg', role: 'group' }, opts.map(([v, label]) => (btns[v] = h('button', { type: 'button', class: 'segb', onclick: () => { onPick(v); mark(v); } }, label))));
        function mark(v) { Object.keys(btns).forEach((k) => { btns[k].classList.toggle('on', k === v); btns[k].setAttribute('aria-pressed', String(k === v)); }); }
        mark(cur); return el;
      };
      const modeSeg = seg('rvc.mode', [['auto', 'Automática (ao engatar a ré)'], ['on', 'Sempre ligada'], ['off', 'Desligada']], S.mode,
        (v) => { S.mode = v; IDE.pref.set('rvc.mode', v); IDE.emit('rvc', S); });
      const guideSeg = seg('rvc.guides', [['off', 'Sem linhas'], ['static', 'Linhas fixas'], ['dynamic', 'Seguem o volante']], S.guides,
        (v) => { S.guides = v; IDE.pref.set('rvc.guides', v); IDE.emit('rvc', S); });
      const devSel = h('select', { class: 'field', 'aria-label': IDE.t('Webcam') });
      devSel.addEventListener('change', () => { S.device = devSel.value; IDE.pref.set('rvc.device', S.device); restart(); });
      const mirrorCb = h('input', { type: 'checkbox' }); mirrorCb.checked = S.mirror;
      mirrorCb.addEventListener('change', () => { S.mirror = mirrorCb.checked; IDE.pref.set('rvc.mirror', S.mirror); IDE.emit('rvc', S); });
      const status = h('div', { class: 'rvc-status' });
      const preview = h('video', { class: 'rvc-preview', autoplay: '', muted: '', playsinline: '' }); preview.muted = true;
      const gearBtn = h('button', { class: 'btn', type: 'button' });
      async function setGear(v) { try { await post('/api/can/set', { name: 'gear_position', value: v }); S.gear = v; refresh(); } catch (e) { toastErr(e); } }
      gearBtn.addEventListener('click', () => IDE.busy(gearBtn, () => setGear(S.gear === GEAR_R ? 0 : GEAR_R)));
      const refreshBtn = h('button', { class: 'btn sm', type: 'button', onclick: () => { restart(); listDevices(); } }, ic('refresh', 14), 'Atualizar');

      function refresh() {
        IDE.clear(devSel);
        devSel.appendChild(h('option', { value: '' }, IDE.t('Padrão do sistema')));
        S.devices.forEach((d, i) => devSel.appendChild(h('option', { value: d.deviceId }, d.label || (IDE.t('Webcam') + ' ' + (i + 1)))));
        devSel.value = S.devices.some((d) => d.deviceId === S.device) ? S.device : '';
        mirrorCb.checked = S.mirror; preview.classList.toggle('mirror', S.mirror);
        if (S.stream && preview.srcObject !== S.stream) { preview.srcObject = S.stream; const p = preview.play(); if (p && p.catch) p.catch(() => {}); }
        if (!S.stream && preview.srcObject) preview.srcObject = null;
        status.className = 'rvc-status ' + S.state;
        status.textContent = S.state === 'live' ? IDE.t('Webcam ativa') : S.state === 'starting' ? IDE.t('Abrindo a webcam…') : S.state === 'error' ? IDE.t(S.err) : IDE.t('Webcam desligada');
        IDE.clear(gearBtn); IDE.add(gearBtn, ic('car', 14), S.gear === GEAR_R ? 'Tirar da ré (P)' : 'Engatar a ré');
        gearBtn.classList.toggle('primary-o', S.gear !== GEAR_R); gearBtn.classList.toggle('danger-o', S.gear === GEAR_R);
      }
      const row = (label, el) => h('div', { class: 'rvc-row' }, h('label', { class: 'muted small' }, label), el);
      IDE.add(host, h('div', { class: 'rvc-tab' },
        h('p', { class: 'help' }, 'A câmera de ré usa a webcam do computador. Com a ré engatada no CAN virtual, a imagem aparece sobre o display do carro, com linhas-guia de estacionamento. A imagem só é mostrada aqui, no navegador: o sistema do carro emulado não a recebe, e a webcam só liga enquanto ela está sendo exibida.'),
        row('Quando mostrar', modeSeg),
        row('Webcam', h('div', { class: 'rvc-dev' }, devSel, refreshBtn)),
        row('Linhas-guia', guideSeg),
        h('label', { class: 'rvc-chk' }, mirrorCb, h('span', null, 'Espelhar a imagem')),
        h('div', { class: 'rvc-test' }, gearBtn, h('span', { class: 'muted small' }, 'Muda a marcha no CAN virtual para testar.')),
        status, preview));
      const off = IDE.on('rvc', refresh);
      refresh();
      return {
        show() { acquire(OWNER); listDevices(); refresh(); },
        hide() { release(OWNER); },
        destroy() { release(OWNER); off(); },
      };
    },
  };

  IDE.rvc = { attach, state: S };
})(window.IDE);
