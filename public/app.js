'use strict';

const VARIANTS = [
  { key: 'texas', name: "Texas Hold'em", desc: '2 hole cards. Best 5-card hand from your 2 cards and the 5 community cards.' },
  { key: '999', name: '999', desc: '5 hole cards. Pick 3 to make a number closest to 999 (10, J, Q, K, A count as 0). The other 2 play Texas. Pot splits: half to the best Texas hand, half to the highest number. Ties split their half.' },
  { key: '135', name: '1 3 5', desc: '5 hole cards. Your hand must use exactly 1, 3 or 5 of your hole cards with the community cards.' },
  { key: 'theenpathi', name: 'Theenpathi', desc: '5 hole cards. Pick 3 for a Theenpathi hand (Trail > Straight Flush > Straight > Flush > Pair > High Card). The other 2 play Texas. Pot splits half and half.' },
  { key: 'omaha', name: 'Omaha', desc: '4 hole cards. You must use exactly 2 of them with exactly 3 community cards.' },
];
const SUITS = { s: '♠', h: '♥', d: '♦', c: '♣' };
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let ws = null;
let state = null;
let chat = [];
let session = loadSession();
let pendingSide = [];   // cards picked for 999/Theenpathi before 3 are chosen
let pendingHand = 0;
let pendingUse = null;   // hole cards chosen at showdown (null until the showdown starts)
let raiseKey = '';      // keeps the raise amount while it is still the same decision

function loadSession() {
  // per tab, so a refresh keeps your seat (rejoining with the same name also works)
  try { return JSON.parse(sessionStorage.getItem('poker.session')) || null; } catch { return null; }
}
function saveSession(s) {
  session = s;
  try { s ? sessionStorage.setItem('poker.session', JSON.stringify(s)) : sessionStorage.removeItem('poker.session'); } catch {}
}

// ---------- connection ----------

function connect(first) {
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  ws.onopen = () => {
    if (first) send(first);
    else if (session) send({ type: 'resume', code: session.code, token: session.token });
  };
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.type === 'joined') {
      saveSession({ code: m.code, token: m.token, id: m.id });
      history.replaceState(null, '', '?code=' + m.code);
      show('game');
    } else if (m.type === 'state') {
      state = m.state; chat = m.chat || []; render();
    } else if (m.type === 'kicked') {
      leaveTable(m.message);
    } else if (m.type === 'error') {
      if (/removed you/.test(m.message)) leaveTable(m.message);
      else if (/no longer available|No game with code/.test(m.message) && !state) {
        saveSession(null); show('home'); $('homeErr').textContent = m.message;
      } else if ($('home').classList.contains('hidden')) toast(m.message);
      else $('homeErr').textContent = m.message;
    }
  };
  ws.onclose = () => { if (session) setTimeout(() => connect(), 1500); };
}
function leaveTable(message) {
  saveSession(null);
  state = null;
  history.replaceState(null, '', '/');
  ['chooser', 'ledger', 'rules'].forEach((id) => $(id).classList.add('hidden'));
  show('home');
  $('homeErr').textContent = message;
}
function send(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); }

function show(screen) {
  $('home').classList.toggle('hidden', screen !== 'home');
  $('game').classList.toggle('hidden', screen !== 'game');
}

function toast(msg) {
  const t = $('toast'); t.textContent = msg; t.classList.remove('hidden');
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 3000);
}

// ---------- rendering ----------

function cardHTML(c, size = '', extra = '') {
  if (c === '??') return `<div class="card back ${size} ${extra}"></div>`;
  const r = c[0] === 'T' ? '10' : c[0];
  const red = c[1] === 'h' || c[1] === 'd';
  return `<div class="card ${size} ${red ? 'red' : ''} ${extra}"><span class="r">${r}</span><span class="s">${SUITS[c[1]]}</span></div>`;
}

function me() { return state && state.seats.find((s) => s.id === state.you); }

function render() {
  const s = state, my = me();
  if (!s || !my) return;
  if (s.handNo !== pendingHand) { pendingHand = s.handNo; pendingSide = []; pendingUse = null; }
  $('codeText').textContent = s.code;
  const phaseName = { lobby: 'Waiting to start', choosing: 'Choosing game', preflop: 'Pre-flop', flop: 'Flop', turn: 'Turn', river: 'River', declare: 'Showdown pick', handover: 'Hand over' }[s.phase];
  declareEnd = s.phase === 'declare' ? Date.now() + s.declareLeft * 1000 : 0;
  $('handInfo').textContent = s.started ? `Hand #${s.handNo} · ${phaseName} · Blinds ${s.blinds[0]}/${s.blinds[1]}` : `Blinds ${s.blinds[0]}/${s.blinds[1]} · ${s.startingChips} chips each`;
  $('variantLabel').textContent = s.variantName || (s.phase === 'choosing' ? 'Small blind is choosing…' : '');
  $('board').innerHTML = s.board.map((c) => cardHTML(c)).join('');
  $('pot').textContent = s.pot ? `Pot ${s.pot}` : '';

  renderLobby(s, my);
  renderSeats(s);
  renderMine(s, my);
  renderActions(s, my);
  renderResult(s);
  renderLog(s);

  $('rebuyBtn').textContent = my.pendingBuyins ? `Buy in +200 (${my.pendingBuyins} pending)` : 'Buy in +200';
  renderScore(s);
  $('cashoutBtn').textContent = my.pendingCashout ? 'Cashing out after hand…' : my.cashedOut ? 'Cashed out' : 'Cash out';
  $('cashoutBtn').disabled = my.cashedOut || my.pendingCashout;
  if (!$('ledger').classList.contains('hidden')) renderLedger(s);
  $('sitBtn').textContent = my.sittingOut ? "I'm back" : 'Sit out';
  $('chooser').classList.toggle('hidden', !(s.phase === 'choosing' && s.chooser === s.you));
}

function renderLobby(s, my) {
  const box = $('lobbyBox');
  if (s.started) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  const isHost = s.hostId === s.you;
  box.innerHTML = `
    <div>Share this code with your friends</div>
    <div class="big-code">${esc(s.code)}</div>
    <div>${s.seats.filter((p) => !p.kicked).length} player${s.seats.filter((p) => !p.kicked).length === 1 ? '' : 's'} at the table</div>
    ${isHost ? `<button class="btn primary" id="startBtn" ${s.canStart ? '' : 'disabled'}>${s.canStart ? 'Start game' : 'Need 2+ players'}</button>`
             : '<div style="color:rgba(255,255,255,.7)">Waiting for the host to start…</div>'}`;
  const b = $('startBtn'); if (b) b.onclick = () => send({ type: 'start' });
}

function seatPositions(n) {
  // my seat at the bottom, the rest clockwise around the oval
  const narrow = window.innerWidth <= 640;
  const rx = narrow ? 38 : 45, ry = narrow ? 42 : 43;
  return Array.from({ length: n }, (_, i) => {
    const a = Math.PI / 2 + (i * 2 * Math.PI) / n;
    return { x: 50 + rx * Math.cos(a), y: 50 + ry * Math.sin(a), bx: 50 + rx * 0.58 * Math.cos(a), by: 50 + ry * 0.55 * Math.sin(a) };
  });
}

function renderSeats(s) {
  const seated = s.seats.filter((p) => !p.kicked);
  const n = seated.length;
  const myIdx = seated.findIndex((x) => x.id === s.you);
  const isHost = s.hostId === s.you;
  const pos = seatPositions(n);
  const hands = (s.result && s.result.hands) || {};
  const winners = new Set();
  if (s.result) s.result.pots.forEach((p) => p.awards.forEach((a) => winners.add(a.id)));
  let html = '';
  seated.forEach((p, i) => {
    const k = (i - myIdx + n) % n, at = pos[k];
    const canKick = isHost && p.id !== s.you;
    const cls = ['seat', p.turn && 'turn', p.id === s.you && 'me', p.folded && 'folded', !p.connected && 'offline', canKick && 'kickable'].filter(Boolean).join(' ');
    const showCards = p.id !== s.you || s.phase === 'handover';
    const h = hands[p.id];
    const cards = showCards ? p.cards.map((c, ci) => cardHTML(c, 'sm', h && !h.mucked ? cardRole(h, ci) : '')).join('') : '';
    let desc = '';
    if (h && s.phase === 'handover') {
      desc = h.mucked ? '<div class="hand-desc">Mucked</div>'
        : `<div class="hand-desc">${esc(h.main)}${h.side ? `<span class="side-d">${esc(s.result.sideName)}: ${esc(h.side)}</span>` : ''}</div>`;
    }
    const picking = s.phase === 'declare' && p.inHand && !p.folded;
    const status = picking ? (p.declared ? 'Ready ✓' : 'Picking…') : p.cashedOut ? 'Cashed out' : p.allIn ? 'All-in' : (!p.inHand && s.started ? (p.chips === 0 ? 'Out of chips' : p.sittingOut ? 'Sitting out' : 'Next hand') : p.lastAction);
    html += `<div class="${cls}" style="left:${at.x}%;top:${at.y}%"${canKick ? ` data-kick="${esc(p.id)}" title="Remove ${esc(p.name)}"` : ''}>
      <div class="cards">${cards}</div>
      <div class="plate">${canKick ? '<span class="kick-x" aria-hidden="true">✕</span>' : ''}
        <div class="badges">
          ${p.id === s.hostId ? '<span class="badge host">HOST</span>' : ''}
          ${p.dealer ? '<span class="badge d">D</span>' : ''}${p.sb ? '<span class="badge sb">SB</span>' : ''}${p.bb ? '<span class="badge bb">BB</span>' : ''}
        </div>
        <div class="name">${winners.has(p.id) ? '🏆 ' : ''}${esc(p.name)}</div>
        <div class="chips">${p.chips}</div>
        <div class="act">${esc(status || '')}</div>
      </div>${desc}
    </div>`;
    if (p.bet > 0) html += `<div class="bet-chip" style="left:${at.bx}%;top:${at.by}%">${p.bet}</div>`;
  });
  $('seats').innerHTML = html;
}

// Theenpathi 3-card hand name (same ranking as the server): Trail > Straight Flush > Straight > Flush > Pair > High Card
const RANK_VAL = { 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, T: 10, J: 11, Q: 12, K: 13, A: 14 };
const RANK_NAME = { 2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight', 9: 'Nine', 10: 'Ten', 11: 'Jack', 12: 'Queen', 13: 'King', 14: 'Ace' };
const plural = (r) => (r === 6 ? 'Sixes' : RANK_NAME[r] + 's');
function tpName(cards) {
  const rs = cards.map((c) => RANK_VAL[c[0]]).sort((a, b) => b - a);
  const flush = cards.every((c) => c[1] === cards[0][1]);
  let high = 0;
  if (new Set(rs).size === 3) {
    if (rs[0] - rs[2] === 2) high = rs[0];
    else if (rs[0] === 14 && rs[1] === 3 && rs[2] === 2) high = 3;
  }
  if (rs[0] === rs[2]) return `Trail of ${plural(rs[0])}`;
  if (high && flush) return `Straight Flush, ${RANK_NAME[high]} high`;
  if (high) return `Straight, ${RANK_NAME[high]} high`;
  if (flush) return `Flush, ${RANK_NAME[rs[0]]} high`;
  if (rs[0] === rs[1] || rs[1] === rs[2]) return `Pair of ${plural(rs[1])}`;
  return `${RANK_NAME[rs[0]]} High`;
}

function value999(cards) {
  const d = cards.map((c) => ('23456789'.includes(c[0]) ? +c[0] : 0)).sort((a, b) => b - a);
  return String(d[0] * 100 + d[1] * 10 + d[2]).padStart(3, '0');
}

const USE_RULE = {
  texas: 'Use 0, 1 or 2 of your cards (0 = play the board)',
  omaha: 'Use exactly 2 of your 4 cards',
  '135': 'Use exactly 1, 3 or 5 of your cards',
  '999': 'From your other 2 cards, use 0, 1 or 2 for Texas',
  theenpathi: 'From your other 2 cards, use 0, 1 or 2 for Texas',
};

function renderMine(s, my) {
  const box = $('myCards'), info = $('splitInfo');
  const cards = my.cards || [];
  const live = my.inHand && !my.folded && cards.length > 0;
  const declaring = s.phase === 'declare' && live;
  const side = my.sideIdx || pendingSide;
  const use = declaring ? (pendingUse || my.useIdx || []) : [];
  const sideName = s.variant === '999' ? '999' : 'Theenpathi';
  if (declaring && pendingUse === null && !my.declared) {   // start the preview with nothing selected
    pendingUse = my.useIdx || [];
    send({ type: 'use', idx: pendingUse });
  }
  // which click does what: split games pick 3 side cards on the big row; the Texas pick has its own row
  const sidePick = s.split && live && !my.declared && s.phase !== 'handover';
  const usePick = declaring && !my.declared && !s.split;
  box.innerHTML = cards.map((c, i) => cardHTML(c, 'lg', [
    (sidePick || usePick) && 'pick', s.split && side.includes(i) && 'side-card',
    use.includes(i) && 'use-card', my.folded && 'dim'].filter(Boolean).join(' '))).join('');
  if (sidePick) [...box.children].forEach((el, i) => (el.onclick = () => toggleSide(i)));
  if (usePick) [...box.children].forEach((el, i) => (el.onclick = () => toggleUse(i)));

  if (!live) {
    info.textContent = !my.inHand && s.started && s.phase !== 'handover'
      ? (my.chips === 0 ? 'You are out of chips — press Buy in to keep playing.' : 'You will be dealt in next hand.') : '';
    return;
  }
  let html = '';
  if (s.split) {
    if (side.length === 3) {
      const sc = side.map((i) => cards[i]);
      html += `<div><b>${sideName}:</b> <span class="t">${sc.map(pretty).join(' ')} = ${s.variant === '999' ? value999(sc) : tpName(sc)}</span></div>`;
    } else if (s.phase !== 'handover') {
      html += `<div>Click <b>3 cards</b> for your ${sideName} hand — the other 2 are for Texas. (${3 - side.length} more)</div>`;
    }
    if (!declaring && s.phase !== 'handover') html += '<div>Change it any time — you make your final pick at showdown.</div>';
  }
  if (declaring && !my.declared) {
    const sideDone = !s.split || side.length === 3;
    if (s.split) html = `<div class="step">Step 1 — your ${sideName} cards:</div>` + html;
    if (sideDone) {
      html += `<div class="step">${s.split ? 'Step 2 — ' : 'Showdown: '}${USE_RULE[s.variant]}.</div>`;
      if (s.split) {
        const rest = cards.map((c, i) => i).filter((i) => !side.includes(i));
        html += `<div class="use-row">${rest.map((i) => cardHTML(cards[i], '', `pick ${use.includes(i) ? 'use-card' : ''}" data-i="${i}`)).join('')}</div>`;
      }
      html += previewHTML(s, cards, use);
    }
    const ok = s.preview && s.preview.desc && (!s.split || side.length === 3);
    html += `<div class="declare-row"><button id="declareBtn" class="btn primary small" ${ok ? '' : 'disabled'}>Confirm my cards</button>` +
      ' <span class="declare-count"></span> <span class="muted">If you don\'t confirm in time, you muck.</span></div>';
  } else if (declaring) {
    html += previewHTML(s, cards, use);
    html += '<div class="declare-row">✓ Confirmed — waiting for the others… <span class="declare-count"></span></div>';
  }
  info.innerHTML = html;
  info.querySelectorAll('.use-row .card').forEach((el) => (el.onclick = () => toggleUse(+el.dataset.i)));
  const b = $('declareBtn');
  if (b) b.onclick = () => send({ type: 'declare', use, side: s.split ? side : null });
  tickDeclare();
}

function previewHTML(s, cards, use) {
  const pv = s.preview;
  if (!pv) return '';
  if (pv.error) return use.length ? `<div class="preview bad">${esc(pv.error)}</div>` : '<div class="preview">Click the cards you are using.</div>';
  const mine = use.map((i) => cards[i]);
  return `<div class="preview">Your hand: <b>${esc(pv.desc)}</b> — ` +
    `${mine.length ? `your ${mine.map(pretty).join(' ')} + ` : ''}board ${pv.board.map(pretty).join(' ')}</div>`;
}

function toggleUse(i) {
  const my = me();
  let cur = [...(pendingUse || my.useIdx || [])];
  cur = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i];
  pendingUse = cur;
  send({ type: 'use', idx: cur });
  renderMine(state, my);
}

let declareEnd = 0;
function tickDeclare() {
  const left = Math.max(0, Math.ceil((declareEnd - Date.now()) / 1000));
  document.querySelectorAll('.declare-count').forEach((el) => (el.textContent = `(${left}s)`));
}
setInterval(tickDeclare, 500);

function pretty(c) { return (c[0] === 'T' ? '10' : c[0]) + SUITS[c[1]]; }

function toggleSide(i) {
  const my = me();
  let cur = [...(my.sideIdx || pendingSide)];
  if (cur.includes(i)) cur = cur.filter((x) => x !== i);
  else if (cur.length < 3) cur.push(i);
  else { cur.shift(); cur.push(i); }
  pendingSide = cur;
  if (my.sideIdx) my.sideIdx = null;  // edit locally until 3 are chosen again
  if (cur.length === 3) send({ type: 'split', idx: cur });
  if (pendingUse && pendingUse.some((x) => cur.includes(x))) {  // a card can't be in both hands
    pendingUse = pendingUse.filter((x) => !cur.includes(x));
    send({ type: 'use', idx: pendingUse });
  }
  renderMine(state, my);
}

function renderActions(s, my) {
  const lg = s.legal, acts = $('actions'), wait = $('waitMsg');
  if (!lg) {
    acts.classList.add('hidden');
    const turn = s.seats.find((p) => p.turn);
    if (s.phase === 'choosing') wait.textContent = s.chooser === s.you ? '' : `${turn ? turn.name : 'Small blind'} is choosing the game…`;
    else if (s.phase === 'declare') wait.innerHTML = 'Showdown — players are choosing their cards <span class="declare-count"></span>';
    else if (s.phase === 'handover') wait.textContent = s.canStart ? 'Next hand starting soon…' : 'Waiting for more players with chips…';
    else if (turn && s.started) wait.textContent = `Waiting for ${turn.name}…`;
    else wait.textContent = '';
    return;
  }
  wait.textContent = '';
  acts.classList.remove('hidden');
  $('checkBtn').textContent = lg.canCheck ? 'Check' : (lg.toCall >= my.chips ? `All-in ${lg.toCall}` : `Call ${lg.toCall}`);
  $('foldBtn').disabled = false;
  const rb = $('raiseBox'), raiseBtn = $('raiseBtn');
  raiseBtn.classList.toggle('hidden', !lg.canRaise);
  rb.classList.toggle('hidden', !lg.canRaise);
  if (!lg.canRaise) return;
  const slider = $('raiseSlider'), input = $('raiseInput');
  slider.min = input.min = lg.minTo; slider.max = input.max = lg.maxTo; slider.step = 1;
  const key = `${s.handNo}|${s.phase}|${lg.currentBet}`;
  if (key !== raiseKey) { raiseKey = key; setRaise(lg.minTo); }
  else if (document.activeElement === input) onTyped();  // don't overwrite what's being typed
  else setRaise(+input.value);
}

function clampRaise(v) {
  const lg = state.legal;
  return Math.max(lg.minTo, Math.min(lg.maxTo, Math.round(v) || lg.minTo));
}

function raiseLabel(v) {
  const lg = state.legal;
  return v === lg.maxTo ? `All-in ${v}` : `${lg.currentBet === 0 ? 'Bet' : 'Raise to'} ${v}`;
}

function setRaise(v) {
  const lg = state.legal; if (!lg) return;
  v = clampRaise(v);
  $('raiseSlider').value = v; $('raiseInput').value = v;
  $('raiseBtn').textContent = raiseLabel(v);
  $('raiseBtn').disabled = false;
  const hint = $('raiseHint');
  hint.classList.remove('bad');
  hint.textContent = `Type any amount from ${lg.minTo} to ${lg.maxTo}`;
}

// Typing: keep the box exactly as typed, keep the slider and button in step
function onTyped() {
  const lg = state.legal; if (!lg) return;
  const input = $('raiseInput'), hint = $('raiseHint'), btn = $('raiseBtn');
  const digits = input.value.replace(/\D/g, '');
  if (digits !== input.value) input.value = digits;
  const v = parseInt(digits, 10);
  hint.classList.remove('bad');
  if (!digits) {
    btn.disabled = true; btn.textContent = raiseLabel(lg.minTo);
    hint.textContent = `Type any amount from ${lg.minTo} to ${lg.maxTo}`;
  } else if (v < lg.minTo) {
    btn.disabled = true; btn.textContent = raiseLabel(lg.minTo);
    hint.classList.add('bad'); hint.textContent = `Minimum is ${lg.minTo}`;
  } else {
    const amt = Math.min(v, lg.maxTo);
    $('raiseSlider').value = amt;
    btn.disabled = false; btn.textContent = raiseLabel(amt);
    if (v > lg.maxTo) { hint.classList.add('bad'); hint.textContent = `You only have ${lg.maxTo} — that's all-in`; }
    else hint.textContent = 'Press Enter or the button to bet';
  }
}

function cardRole(h, i) {
  if (h.sideIdx && h.sideIdx.includes(i)) return 'side-card';
  return h.use && h.use.includes(i) ? 'use-card' : 'unused';
}

function renderResult(s) {
  const box = $('result');
  if (s.phase !== 'handover' || !s.result) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  const r = s.result, won = {};
  r.pots.forEach((p) => p.awards.forEach((a) => (won[a.id] = (won[a.id] || 0) + a.amount)));
  let html = '';
  if (!r.uncontested) {
    html += '<div class="sd-title">Showdown</div><div class="sd-rows">';
    s.seats.filter((p) => r.hands[p.id]).sort((a, b) => (won[b.id] || 0) - (won[a.id] || 0)).forEach((p) => {
      const h = r.hands[p.id];
      const hole = p.cards.map((c, i) => cardHTML(c, 'sm', h.mucked ? 'unused' : cardRole(h, i))).join('');
      let detail;
      if (h.mucked) detail = '<span class="muted">Mucked — didn\'t confirm in time</span>';
      else {
        const usedHole = h.use.map((i) => p.cards[i]);
        detail = `<b>${esc(h.main)}</b><div class="sd-made">` +
          `${usedHole.map((c) => cardHTML(c, 'sm', 'use-card')).join('')}` +
          `${usedHole.length ? '<span class="plus">+</span>' : '<span class="muted">board only</span>'}` +
          `${h.board.map((c) => cardHTML(c, 'sm')).join('')}</div>`;
        if (h.side) {
          const sc = h.sideIdx.map((i) => p.cards[i]);
          detail += `<div class="sd-side">${esc(r.sideName)}: ${sc.map((c) => cardHTML(c, 'sm', 'side-card')).join('')} <b>${esc(h.side)}</b></div>`;
        }
      }
      html += `<div class="sd-row ${won[p.id] ? 'won' : ''}">
        <div class="sd-name">${won[p.id] ? '🏆 ' : ''}${esc(p.name)}${won[p.id] ? `<div class="sd-won">+${won[p.id]}</div>` : ''}</div>
        <div class="sd-hole">${hole}</div>
        <div class="sd-detail">${detail}</div></div>`;
    });
    html += '</div>';
  }
  html += r.pots.map((p, i) => {
    const label = r.pots.length > 1 ? (i === 0 ? 'Main pot' : `Side pot ${i}`) : 'Pot';
    return `<div class="pot-line"><b>${label} (${p.amount})</b>: ` +
      p.awards.map((a) => `${esc(a.name)} wins ${a.amount} — ${esc(a.why)}`).join('; ') + '</div>';
  }).join('');
  if (!r.uncontested) html += '<div class="sd-key"><span class="k use"></span> cards used' +
    (r.sideName ? ` <span class="k side"></span> ${esc(r.sideName)} cards` : '') + '</div>';
  box.innerHTML = html;
}

// ---------- ledger ----------

let ledgerSort = { key: 'net', dir: -1 };
const ledgerOpen = new Set();   // player ids whose details are expanded

function ledgerRows(s) {
  return s.seats.map((p) => ({
    id: p.id, name: p.name, you: p.id === s.you, kicked: p.kicked, history: p.history || [], buyins: p.buyins,
    buyin: p.buyinTotal, buyout: p.buyout, stack: p.net - p.buyout + p.buyinTotal, net: p.net,
  }));
}

function fmtNet(n) { return n > 0 ? `+${n}` : `${n}`; }
function fmtTime(t) { return new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }

function renderLedger(s) {
  const rows = ledgerRows(s).sort((a, b) => ledgerSort.dir * (a[ledgerSort.key] - b[ledgerSort.key]) || a.name.localeCompare(b.name));
  document.querySelectorAll('.ledger-table th[data-sort]').forEach((th) => {
    th.classList.toggle('sorted', th.dataset.sort === ledgerSort.key);
    th.dataset.arrow = th.dataset.sort === ledgerSort.key ? (ledgerSort.dir < 0 ? '↓' : '↑') : '';
  });
  $('ledgerBody').innerHTML = rows.map((r) => {
    const cls = r.net > 0 ? 'up' : r.net < 0 ? 'down' : '';
    let html = `<tr class="lrow ${r.you ? 'me' : ''}">
      <td class="l" data-details="${esc(r.id)}"><span class="lname">${esc(r.name)}${r.kicked ? ' <span class="removed">removed</span>' : ''}<span class="caret">${ledgerOpen.has(r.id) ? '▴' : '▾'}</span></span> <span class="lid">@ ${esc(r.id)}</span></td>
      <td class="ldet"><button class="btn tiny ghost" data-details="${esc(r.id)}">${ledgerOpen.has(r.id) ? 'Hide' : 'Details'}</button></td>
      <td>${r.buyin}</td><td>${r.buyout}</td><td>${r.stack}</td><td class="${cls}">${fmtNet(r.net)}</td></tr>`;
    if (ledgerOpen.has(r.id)) {
      html += `<tr class="ldetail"><td colspan="6"><div class="ldetail-box">
        <div class="muted">${r.buyins} buy-in${r.buyins === 1 ? '' : 's'} · ${r.history.filter((h) => h.kind === 'Buy-out').length} cash-out(s)</div>
        ${r.history.map((h) => `<div class="lev"><span>${fmtTime(h.t)}</span><span class="${h.kind === 'Buy-in' ? 'in' : 'out'}">${h.kind}</span><b>${h.amount}</b></div>`).join('')}
      </div></td></tr>`;
    }
    return html;
  }).join('');
  const tot = rows.reduce((a, r) => ({ buyin: a.buyin + r.buyin, buyout: a.buyout + r.buyout, stack: a.stack + r.stack, net: a.net + r.net }),
    { buyin: 0, buyout: 0, stack: 0, net: 0 });
  $('ledgerFoot').innerHTML = `<tr><td class="l">Total</td><td class="ldet"></td><td>${tot.buyin}</td><td>${tot.buyout}</td><td>${tot.stack}</td><td>${fmtNet(tot.net)}</td></tr>`;
}

function downloadLedger() {
  const rows = ledgerRows(state).sort((a, b) => b.net - a.net);
  const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [['Player', 'ID', 'Buy-ins (count)', 'Buy-in', 'Buy-out', 'Stack', 'Net'].map(q).join(',')];
  rows.forEach((r) => lines.push([r.name, r.id, r.buyins, r.buyin, r.buyout, r.stack, r.net].map(q).join(',')));
  lines.push('', ['Player', 'Time', 'Event', 'Amount'].map(q).join(','));
  rows.forEach((r) => r.history.forEach((h) => lines.push([r.name, new Date(h.t * 1000).toLocaleString(), h.kind, h.amount].map(q).join(','))));
  const blob = new Blob([lines.join('\r\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `poker-ledger-${state.code}-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function renderScore(s) {
  const rows = [...s.seats].sort((a, b) => b.net - a.net).map((p) => {
    const net = p.net > 0 ? `+${p.net}` : `${p.net}`;
    const pend = p.pendingBuyins ? ` <span class="pend">+${p.pendingBuyins}</span>` : '';
    return `<tr class="${p.id === s.you ? 'me' : ''}"><td>${esc(p.name)}${p.kicked ? ' <span class="removed">removed</span>' : ''}</td><td>${p.buyins}${pend}</td>` +
      `<td>${p.chips}</td><td class="${p.net > 0 ? 'up' : p.net < 0 ? 'down' : ''}">${net}</td></tr>`;
  }).join('');
  $('score').innerHTML = `<tr><th>Player</th><th>Buy-ins</th><th>Chips</th><th>+/−</th></tr>${rows}`;
}

function renderLog(s) {
  const log = $('log');
  const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
  log.innerHTML = s.log.map((l) => `<div class="${l.startsWith('---') ? 'hr' : ''}">${esc(l)}</div>`).join('');
  if (atBottom) log.scrollTop = log.scrollHeight;
  const c = $('chat');
  const cBottom = c.scrollTop + c.clientHeight >= c.scrollHeight - 20;
  c.innerHTML = chat.map((m) => `<div><b>${esc(m.name)}:</b> ${esc(m.text)}</div>`).join('');
  if (cBottom) c.scrollTop = c.scrollHeight;
}

// ---------- wiring ----------

function variantCards(el, clickable) {
  el.innerHTML = VARIANTS.map((v) => `<${clickable ? 'button' : 'div'} class="variant" data-v="${v.key}"><h4>${v.name}</h4><p>${v.desc}</p></${clickable ? 'button' : 'div'}>`).join('');
}
variantCards($('variantList'), true);
$('variantList').onclick = (e) => {
  const b = e.target.closest('[data-v]'); if (b) send({ type: 'choose', variant: b.dataset.v });
};

const nameInput = $('name');
nameInput.value = localStorage.getItem('poker.name') || '';
const urlCode = new URLSearchParams(location.search).get('code');
if (urlCode) $('joinCode').value = urlCode.toUpperCase();

function start(type) {
  const name = nameInput.value.trim();
  if (!name) { $('homeErr').textContent = 'Enter your name first'; nameInput.focus(); return; }
  try { localStorage.setItem('poker.name', name); } catch {}
  $('homeErr').textContent = '';
  const msg = type === 'create' ? { type, name } : { type, name, code: $('joinCode').value.trim().toUpperCase() };
  if (type === 'join' && !msg.code) { $('homeErr').textContent = 'Enter a game code'; return; }
  saveSession(null);
  if (ws) { ws.onclose = null; ws.close(); }
  connect(msg);
  ws.addEventListener('close', () => { if (!session && !$('homeErr').textContent) $('homeErr').textContent = 'Could not reach the server'; });
}
$('hostBtn').onclick = () => start('create');
$('joinBtn').onclick = () => start('join');
$('joinCode').onkeydown = (e) => { if (e.key === 'Enter') start('join'); };

$('foldBtn').onclick = () => {
  if (state.legal && state.legal.canCheck && !confirm('You can check for free. Fold anyway?')) return;
  send({ type: 'act', action: 'fold' });
};
$('checkBtn').onclick = () => send({ type: 'act', action: state.legal.canCheck ? 'check' : 'call' });
$('raiseBtn').onclick = () => {
  const v = parseInt($('raiseInput').value, 10);
  if (!state.legal || !(v >= state.legal.minTo)) return;
  send({ type: 'act', action: 'raise', amount: clampRaise(v) });
};
$('raiseSlider').oninput = (e) => setRaise(+e.target.value);
$('raiseInput').oninput = onTyped;
$('raiseInput').onfocus = (e) => e.target.select();
$('raiseInput').onblur = (e) => { if (state.legal && parseInt(e.target.value, 10) >= state.legal.minTo) setRaise(+e.target.value); };
$('raiseInput').onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); $('raiseBtn').click(); } };
document.querySelector('.presets').onclick = (e) => {
  const p = e.target.dataset.p, lg = state.legal; if (!p || !lg) return;
  const potAfterCall = state.pot + lg.toCall;
  const v = { min: lg.minTo, all: lg.maxTo, half: lg.currentBet + Math.floor(potAfterCall / 2), pot: lg.currentBet + potAfterCall }[p];
  setRaise(v);
};
$('rebuyBtn').onclick = () => {
  const my = me(), inHand = my && my.inHand && !my.folded && !['lobby', 'handover'].includes(state.phase);
  const msg = `Buy in for another ${state.startingChips} chips?` + (inHand ? ' You are in a hand, so they will be added when it ends.' : '');
  if (confirm(msg)) send({ type: 'rebuy' });
};
$('sitBtn').onclick = () => send({ type: 'sitout', value: !(me() && me().sittingOut) });
function openRules(tab) {
  const want = tab || (state && state.variant) || 'general';
  document.querySelectorAll('.rtab').forEach((b) => b.classList.toggle('active', b.dataset.tab === want));
  document.querySelectorAll('.rpage').forEach((p) => p.classList.toggle('active', p.dataset.page === want));
  $('rules').classList.remove('hidden');
}
$('rulesBtn').onclick = () => openRules();
document.querySelectorAll('.rules-link').forEach((l) => (l.onclick = (e) => { e.preventDefault(); openRules('general'); }));
document.querySelector('.rules-tabs').onclick = (e) => { const t = e.target.dataset.tab; if (t) openRules(t); };
$('rules').onclick = (e) => { if (e.target.id === 'rules') $('rules').classList.add('hidden'); };
// phone: the top buttons live in a menu that closes after each choice
$('menuBtn').onclick = (e) => {
  e.stopPropagation();
  const open = $('topActions').classList.toggle('open');
  $('menuBtn').setAttribute('aria-expanded', open);
};
$('topActions').addEventListener('click', () => $('topActions').classList.remove('open'));
document.addEventListener('click', (e) => { if (!e.target.closest('#topActions, #menuBtn')) $('topActions').classList.remove('open'); });
$('ledgerBtn').onclick = () => { $('ledger').classList.remove('hidden'); renderLedger(state); };
$('ledgerClose').onclick = () => $('ledger').classList.add('hidden');
$('ledger').onclick = (e) => { if (e.target.id === 'ledger') $('ledger').classList.add('hidden'); };
$('ledgerDownload').onclick = downloadLedger;
$('seats').onclick = (e) => {
  const seat = e.target.closest('[data-kick]');
  if (!seat || !state || state.hostId !== state.you) return;
  const p = state.seats.find((x) => x.id === seat.dataset.kick);
  if (!p) return;
  const inHand = p.inHand && !p.folded && !['lobby', 'handover'].includes(state.phase);
  if (confirm(`Remove ${p.name} from the table?` + (inHand ? ' They will fold this hand.' : '') +
      ` Their ${p.chips} chips will be cashed out in the ledger, and they won't be able to rejoin this game.`)) {
    send({ type: 'kick', id: p.id });
  }
};
document.querySelector('.ledger-table thead').onclick = (e) => {
  const k = e.target.dataset.sort; if (!k) return;
  ledgerSort = ledgerSort.key === k ? { key: k, dir: -ledgerSort.dir } : { key: k, dir: -1 };
  renderLedger(state);
};
$('ledgerBody').onclick = (e) => {
  const el = e.target.closest('[data-details]'); if (!el) return;
  const id = el.dataset.details;
  ledgerOpen.has(id) ? ledgerOpen.delete(id) : ledgerOpen.add(id);
  renderLedger(state);
};
$('cashoutBtn').onclick = () => {
  const my = me(); if (!my) return;
  const inHand = my.inHand && !my.folded && !['lobby', 'handover'].includes(state.phase);
  const msg = `Cash out ${my.chips} chips and leave the table?` + (inHand ? ' You are in a hand, so it happens when the hand ends.' : '') +
    ' You can come back later with Buy in.';
  if (confirm(msg)) send({ type: 'cashout' });
};
$('rulesClose').onclick = () => $('rules').classList.add('hidden');
$('codeBox').onclick = async () => {
  const link = `${location.origin}/?code=${state.code}`;
  try { await navigator.clipboard.writeText(link); $('copyMsg').textContent = 'copied!'; }
  catch { prompt('Invite link', link); }
  setTimeout(() => ($('copyMsg').textContent = 'copy link'), 1500);
};
$('chatForm').onsubmit = (e) => {
  e.preventDefault();
  const t = $('chatInput').value.trim(); if (t) send({ type: 'chat', text: t });
  $('chatInput').value = '';
};
window.addEventListener('resize', () => state && renderSeats(state));

// Resume a seat after a refresh if this browser was already at a table
if (session && (!urlCode || urlCode.toUpperCase() === session.code)) { show('game'); connect(); }
else show('home');
