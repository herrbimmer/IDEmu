'use strict';
/* IDEmu – aba "CarPlay" (só iDrive 5/6): o iPhone falso que faz o HMI mostrar as telas reais do CarPlay (GET/POST /api/carplay, idemu/carplay.py). */
(function (IDE) {
  const { h, ic, api, post, toastErr } = IDE;

  const STATE = {
    off: ['Desconectado', 'muted'],
    connecting: ['Conectando…', 'warn'],
    connected: ['Conectado', 'ok'],
    disconnecting: ['Desconectando…', 'warn'],
    error: ['Erro', 'danger'],
  };

  IDE.tabDefs.carplay = {
    mount(host) {
      let stop = null, busy = false;
      const cb = h('input', { type: 'checkbox', role: 'switch', 'aria-label': 'Conectar iPhone falso' });
      const keysCb = h('input', { type: 'checkbox', role: 'switch', 'aria-label': 'Mostrar teclas', disabled: true });
      const badge = h('span', { class: 'badge muted hidden' });
      const step = h('div', { class: 'muted small cp-step' });
      const err = h('div', { class: 'note danger hidden' }, ic('alert', 16), h('span', { class: 'cp-err' }));
      const unavailable = h('div', { class: 'note warn hidden' }, ic('alert', 16), h('span', { class: 'cp-una' }));
      const setupBtn = h('button', { class: 'btn sm primary', type: 'button' }, ic('wrench', 14), 'Configurar CarPlay');
      const setupMsg = h('span', { class: 'cp-setup-msg' });
      const setup = h('div', { class: 'note warn hidden cp-setup' }, ic('alert', 16),
        h('div', null, h('div', null, 'O CarPlay não está configurado neste ambiente: o HMI não oferece o CarPlay e o iPhone falso não conecta.'),
          h('div', { class: 'muted small' }, setupMsg), h('div', { class: 'row', style: { 'margin-top': '8px' } }, setupBtn)));
      let flashing = false;

      cb.addEventListener('change', async () => {
        busy = true; cb.disabled = true;
        try { render(await post('/api/carplay', { fake_iphone: cb.checked })); } catch (e) { toastErr(e); cb.checked = !cb.checked; }
        finally { busy = false; cb.disabled = false; }
      });
      setupBtn.addEventListener('click', async () => {
        if (!await IDE.confirm({ title: 'Configurar CarPlay', message: 'Liga o CarPlay neste ambiente como no carro codificado: Connectivity, as variantes do CarPlay e do Bluetooth e CARPLAY_SWT = 1. A codificação atual vai para um backup e a head unit reinicia.', confirmLabel: 'Configurar e reiniciar', icon: 'wrench' })) return;
        await IDE.busy(setupBtn, async () => { try { render(await post('/api/carplay', { setup: true })); } catch (e) { toastErr(e); } });
      });
      keysCb.addEventListener('change', async () => {
        busy = true; keysCb.disabled = true;
        try { render(await post('/api/carplay', { show_keys: keysCb.checked })); } catch (e) { toastErr(e); keysCb.checked = !keysCb.checked; }
        finally { busy = false; }
      });

      IDE.add(host, h('div', { class: 'carplay' },
        h('fieldset', null, h('legend', null, 'iPhone falso'),
          h('div', { class: 'row between wrap' },
            h('label', { class: 'switch' }, cb, h('span', { class: 'track' }), h('span', { class: 'sw-lab' }, 'Conectar iPhone falso')),
            badge),
          step,
          h('p', { class: 'help' }, 'Simula um iPhone pareado por Bluetooth com o CarPlay conectado: o HMI mostra a entrada CarPlay no menu principal e passa para a tela do CarPlay. Não há imagem de um celular: a área de vídeo do CarPlay mostra um marcador.'),
          h('label', { class: 'switch cp-keys' }, keysCb, h('span', { class: 'track' }), h('span', { class: 'sw-lab' }, 'Mostrar teclas')),
          h('p', { class: 'help' }, 'Lista no canto da tela do CarPlay os códigos que o HMI manda ao CarPlay a cada tecla do controlador e a cada toque na tela. Só com o CarPlay conectado.'),
          err, unavailable, setup),
        h('div', { class: 'note' }, ic('info', 16),
          h('span', null, 'A conexão de um iPhone real ainda não foi implementada: o iPhone só aceita um acessório CarPlay com o chip de autenticação MFi da Apple, e o hardware emulado não tem esse chip. Provavelmente dá para implementá-la integrando um adaptador (dongle) CarPlay, que tem o chip.'))));

      function render(d) {
        const [label, kind] = STATE[d.state] || [d.state, 'muted'];
        badge.className = 'badge ' + kind; badge.textContent = IDE.t(label);      // className também tira o .hidden
        if (!busy) cb.checked = d.state === 'connecting' || d.state === 'connected';
        step.textContent = d.step ? IDE.t('Aguardando: {step}', { step: d.step }) : '';
        err.classList.toggle('hidden', !d.error); err.querySelector('.cp-err').textContent = d.error || '';
        if (!busy) keysCb.checked = !!d.show_keys;
        keysCb.disabled = busy || d.state !== 'connected';      // só com o CarPlay conectado
        const fl = d.flash || {}, missing = d.missing || [];
        flashing = fl.state === 'running';
        setup.classList.toggle('hidden', !flashing && !missing.length && fl.state !== 'error');
        setupBtn.hidden = flashing || !missing.length;
        setupMsg.textContent = flashing ? IDE.t('Configurando: {step}', { step: IDE.t((fl.steps || [])[fl.step] || '') })
          : fl.state === 'error' ? IDE.t('A configuração falhou: {err}', { err: IDE.t(fl.error || '') })
          : missing.length ? IDE.t('Falta: {list}', { list: missing.join(', ') }) : '';
        unavailable.classList.add('hidden'); cb.disabled = busy || flashing || (!!missing.length && d.state === 'off');
      }
      async function load() {
        try { render(await api('/api/carplay')); }
        catch (e) { badge.classList.add('hidden'); unavailable.classList.remove('hidden'); unavailable.querySelector('.cp-una').textContent = IDE.t(e.message); cb.disabled = true; keysCb.disabled = true; }
      }
      return { show() { stop = IDE.loop(load, 1000); }, hide() { if (stop) stop(); stop = null; }, destroy() { if (stop) stop(); } };
    },
  };
})(window.IDE);
