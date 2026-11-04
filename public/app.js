'use strict';

const VARIANTS = [
  { key: 'texas', name: "Texas Hold'em", short: 'TEXAS', desc: '2 hole cards. At showdown tap the 2, 1 or 0 cards you play.' },
  { key: '999', name: '999', short: '999', desc: '5 hole cards. Before the showdown pick 3 for a number closest to 999 (10 J Q K A = 0); the other 2 play Texas. Pot splits half and half.' },
  { key: '135', name: '1 3 5', short: '1 3 5', desc: '5 hole cards. At showdown use exactly 1, 3 or 5 of them.' },
  { key: 'theenpathi', name: 'Theenpathi', short: 'THEENPATHI', desc: '5 hole cards. Before the showdown pick 3 for a Theenpathi hand (Trail > Str. Flush > Straight > Flush > Pair); the other 2 play Texas. Pot splits half and half.' },
  { key: 'omaha', name: 'Omaha', short: 'OMAHA', desc: '4 hole cards. At showdown use exactly 2 of them with 3 community cards.' },
];
const SHORT = Object.fromEntries(VARIANTS.map((v) => [v.key, v.short]));
const SUITS = { s: '♠', h: '♥', d: '♦', c: '♣' };
const ACTIVE = ['choosing', 'preflop', 'flop', 'turn', 'river', 'declare'];
const STREETS = ['preflop', 'flop', 'turn', 'river'];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let ws = null;
let state = null;
let chat = [];
let session = loadSession();
let pendingSide = [];    // cards picked for 999/Theenpathi before 3 are chosen
let pendingHand = 0;
let pendingUse = null;   // hole cards chosen at showdown (null until the showdown starts)
let raiseKey = '';       // keeps the raise amount while it is still the same decision
let raiseOpen = false;
let preAction = null;    // 'checkfold' | 'check' | 'call', played when your turn comes
let preKey = '';
let autoSent = '';
let turnEnd = 0, turnTotal = 0, declareEnd = 0;
let lastTurnKey = '', lastBoard = 0, lastResultHand = 0, seenChat = 0;
const emoteSeen = new Map();
let prefs = loadPrefs();

function loadSession() {
  // per tab, so a refresh keeps your seat (rejoining with the same name also works)
  try { return JSON.parse(sessionStorage.getItem('poker.session')) || null; } catch { return null; }
}
function saveSession(s) {
  session = s;
  try { s ? sessionStorage.setItem('poker.session', JSON.stringify(s)) : sessionStorage.removeItem('poker.session'); } catch {}
}
function loadPrefs() {
  const d = { sound: true, fourColor: false, bbUnits: false };
  try { return Object.assign(d, JSON.parse(localStorage.getItem('poker.prefs')) || {}); } catch { return d; }
}
function savePrefs() {
  try { localStorage.setItem('poker.prefs', JSON.stringify(prefs)); } catch {}
  applyPrefs();
  if (state) render();
}
function applyPrefs() {
  document.body.classList.toggle('fourc', prefs.fourColor);
  $('soundBtn').textContent = prefs.sound ? '🔊' : '🔇';
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
  if (ws) { ws.onclose = null; ws.close(); }
  history.replaceState(null, '', '/');
  ['chooser', 'ledger', 'rules', 'drawer', 'sdModal'].forEach((id) => $(id).classList.add('hidden'));
  show('home');
  $('homeErr').textContent = message || '';
}
function send(msg) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(msg)); }

function show(screen) {
  $('home').classList.toggle('hidden', screen !== 'home');
  $('game').classList.toggle('hidden', screen !== 'game');
  if (screen === 'game') requestAnimationFrame(fitDock);
}

function toast(msg, ok) {
  const t = $('toast'); t.textContent = msg; t.classList.remove('hidden'); t.classList.toggle('ok', !!ok);
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add('hidden'), 3000);
}

// ---------- sounds ----------

let actx = null;
function tone(freqs, dur = 0.12, vol = 0.07, type = 'sine') {
  if (!prefs.sound) return;
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    freqs.forEach((f, i) => {
      const o = actx.createOscillator(), g = actx.createGain(), t0 = actx.currentTime + i * dur * 0.8;
      o.type = type; o.frequency.value = f;
      g.gain.setValueAtTime(vol, t0); g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.connect(g).connect(actx.destination); o.start(t0); o.stop(t0 + dur + 0.02);
    });
  } catch {}
}
const sound = {
  turn: () => tone([660, 880], 0.14, 0.09),
  deal: () => tone([420], 0.05, 0.04, 'triangle'),
  win: () => tone([523, 659, 784], 0.16, 0.07),
};

// ---------- helpers ----------

function me() { return state && state.seats.find((s) => s.id === state.you); }
function seated(s) { return s.seats.filter((p) => p.seat !== null && !p.kicked); }
function isHost(s) { return s.hostId === s.you; }
function inLiveHand(s, p) { return p && p.inHand && ACTIVE.includes(s.phase); }
function fmt(n) {
  if (!prefs.bbUnits || !state) return String(n);
  const v = n / state.settings.bb;
  return `${Number.isInteger(v) ? v : v.toFixed(1)} BB`;
}
function pretty(c) { return (c[0] === 'T' ? '10' : c[0]) + SUITS[c[1]]; }
function nameColor(id) {
  let h = 0; for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return `hsl(${h}, 70%, 68%)`;
}

function cardHTML(c, extra = '', attrs = '') {
  if (c === '??') return `<div class="card back ${extra}"${attrs}></div>`;
  const r = c[0] === 'T' ? '10' : c[0];
  const red = c[1] === 'h' || c[1] === 'd';
  return `<div class="card s${c[1]} ${red ? 'red' : ''} ${extra}"${attrs}><span class="r">${r}</span><span class="s">${SUITS[c[1]]}</span></div>`;
}

// ---------- rendering ----------

function render() {
  const s = state, my = me();
  if (!s || !my) return;
  if (s.handNo !== pendingHand) { pendingHand = s.handNo; pendingSide = []; pendingUse = null; raiseOpen = false; preAction = null; }
  const pk = `${s.handNo}|${s.phase}`;
  if (pk !== preKey) { preKey = pk; if (preAction === 'check') preAction = null; }
  turnEnd = s.turnLeft ? Date.now() + s.turnLeft * 1000 : 0;
  turnTotal = s.settings.turn;
  declareEnd = s.phase === 'declare' ? Date.now() + s.declareLeft * 1000 : 0;

  const host = s.seats.find((p) => p.id === s.hostId);
  $('ownerName').textContent = (host ? host.name : '—') + (s.started ? ` · hand #${s.handNo}` : '');
  $('gameType').innerHTML = `${esc(s.variant ? SHORT[s.variant] : "SB'S CHOICE")} ~ ${s.blinds[0]} / ${s.blinds[1]}` +
    (s.settings.ante ? ` <small>ante ${s.settings.ante}</small>` : '');
  $('codeText').textContent = s.code;
  $('watermark').textContent = s.variantName ? s.variantName.toUpperCase() : 'POKER NIGHT';

  if (s.board.length > lastBoard || (s.board.length === 0 && lastBoard)) { if (s.board.length) sound.deal(); }
  const newCards = s.board.length > lastBoard ? lastBoard : 99;
  lastBoard = s.board.length;
  $('board').innerHTML = s.board.map((c, i) => cardHTML(c, (i >= newCards ? 'deal ' : '') + boardRole(s, c))).join('');
  const pot = $('pot');
  pot.classList.toggle('hidden', !s.pot);
  pot.innerHTML = `<small>POT</small>${fmt(s.pot)}`;

  renderSeats(s, my);
  renderMine(s, my);
  renderActions(s, my);
  renderCenter(s, my);
  renderRequests(s);
  renderChat();
  if (!$('drawer').classList.contains('hidden')) renderDrawer(s, my, false);
  if (!$('ledger').classList.contains('hidden')) { renderLedger(s); renderFullLog(s); }
  if (!$('sdModal').classList.contains('hidden') && s.phase !== 'handover') $('sdModal').classList.add('hidden');
  $('chooser').classList.toggle('hidden', !(s.phase === 'choosing' && s.chooser === s.you && !s.paused));

  if (s.result && s.phase === 'handover' && lastResultHand !== s.handNo) {
    lastResultHand = s.handNo;
    if (s.result.pots.some((p) => p.awards.some((a) => a.id === s.you && !a.why.startsWith('Uncalled')))) sound.win();
  }
  tick();
  fitDock();
}

function boardRole(s, c) {
  // after a showdown, light up the board cards the winners used
  if (s.phase !== 'handover' || !s.result || s.result.uncontested) return '';
  const winners = new Set();
  s.result.pots.forEach((p) => p.awards.forEach((a) => { if (!a.why.startsWith('Uncalled') && !/^(999|Theenpathi):/.test(a.why)) winners.add(a.id); }));
  return [...winners].some((id) => (s.result.hands[id] && s.result.hands[id].board || []).includes(c)) ? 'win-card' : '';
}

// seat slots as % of the table area, slot 0 = bottom centre, then clockwise
const DESK = [[50, 89], [17, 79], [6.5, 47], [18, 12], [50, 5], [82, 12], [93.5, 47], [83, 79]];
const PHONE = [[50, 90], [15, 74], [12, 45], [18, 15], [50, 6], [82, 15], [88, 45], [85, 74]];
function slotPos(k) { return (window.innerWidth <= 700 ? PHONE : DESK)[k]; }

function renderSeats(s, my) {
  const max = s.maxSeats;
  const base = my.seat !== null ? my.seat : (my.seatRequest !== null ? my.seatRequest : 0);
  const hands = (s.result && s.phase === 'handover' && s.result.hands) || {};
  const won = {};
  if (s.result && s.phase === 'handover') s.result.pots.forEach((p) => p.awards.forEach((a) => { if (!a.why.startsWith('Uncalled')) won[a.id] = true; }));
  const canSit = my.seat === null && my.seatRequest === null;
  const narrow = window.innerWidth <= 700;
  let html = '';
  for (let n = 0; n < max; n++) {
    const k = (n - base + max) % max;
    const [x, y] = slotPos(k);
    const p = s.seats.find((q) => q.seat === n && !q.kicked);
    const pos = `left:${x}%;top:${y}%`;
    if (!p) {
      const asker = s.seats.find((q) => q.seatRequest === n);
      if (asker) {
        const mine = asker.id === s.you;
        html += `<div class="seat empty asked${mine ? ' can-sit' : ''}" style="${pos}" ${mine ? 'data-unsit="1"' : ''}><div class="open"><span class="num">${n + 1}</span>
          <div><b>${esc(asker.name)}</b><br>${mine ? 'waiting for host…<br>tap to cancel' : 'waiting for host'}</div></div></div>`;
      } else {
        html += `<div class="seat empty ${canSit ? 'can-sit' : 'no-sit'}" style="${pos}" ${canSit ? `data-sit="${n}"` : ''}>
          <div class="open"><span class="num">${n + 1}</span>SIT</div></div>`;
      }
      continue;
    }
    const isMe = p.id === s.you;
    const h = hands[p.id];
    const cls = ['seat', isMe && 'me', p.turn && 'turn', p.folded && p.inHand && 'folded', !p.connected && 'offline', won[p.id] && 'winner'].filter(Boolean).join(' ');
    let cards = '';
    if (p.inHand && p.folded && s.phase !== 'lobby') cards = '<div class="fold-mark"><b>✕</b>FOLD</div>';
    else if (isMe) cards = myCardsHTML(s, p);
    else cards = p.cards.map((c, ci) => cardHTML(c, h && !h.mucked ? cardRole(h, ci) : '')).join('');
    const nCards = p.folded ? 0 : p.cards.length;
    const picking = s.phase === 'declare' && p.inHand && !p.folded;
    let status = '';
    if (picking) status = p.declared ? 'READY ✓' : 'CHOOSING…';
    else if (p.pendingCashout) status = 'LEAVING';
    else if (p.sittingOut) status = 'AWAY';
    else if (!p.connected) status = 'OFFLINE';
    else if (p.allIn && p.inHand && ACTIVE.includes(s.phase)) status = 'ALL IN';
    else if (!p.inHand && s.started && ACTIVE.includes(s.phase)) status = p.chips === 0 ? 'NO CHIPS' : 'NEXT HAND';
    else if (p.chips === 0 && s.phase !== 'lobby' && !ACTIVE.includes(s.phase)) status = 'NO CHIPS';
    const rebuys = p.buyins - 1;
    let em = '';
    if (p.emote) {
      const key = `${p.id}|${p.emote.t}`;
      if (!emoteSeen.has(key)) emoteSeen.set(key, Date.now());
      if (Date.now() - emoteSeen.get(key) < 3200) em = `<div class="emote" data-ek="${esc(key)}">${esc(p.emote.e)}</div>`;
    }
    let desc = '';
    if (h) {
      desc = h.mucked ? '<div class="hand-name muck">MUCKED</div>'
        : `<div class="hand-name">${esc(h.main)}${h.side ? `<span class="side-d">${esc(s.result.sideName)}: ${esc(h.side)}</span>` : ''}</div>`;
    }
    html += `<div class="${cls}" style="${pos}">${em}
      <div class="seat-cards n${nCards}">${cards}</div>
      <div class="plate">
        <div class="stats">${p.id === s.hostId ? '<span class="stat host" title="Host">★</span>' : ''}${p.handsWon ? `<span class="stat won" title="Hands won">🏆 ${p.handsWon}</span>` : ''}${rebuys > 0 ? `<span class="stat rebuy" title="Rebuys">↻ ${rebuys}</span>` : ''}</div>
        <div class="pname">${esc(p.name)}</div>
        <div class="pstack">${fmt(p.chips)}</div>
        ${status ? `<div class="pstatus">${status}</div>` : ''}
        ${p.turn && turnTotal ? '<div class="tbar" style="width:100%"></div>' : ''}
      </div>${desc}
    </div>`;
    const word = bubbleWord(p.lastAction);
    const showBubble = word && STREETS.includes(s.phase) && !p.folded;
    if (p.bet > 0 || showBubble) {
      const fx = narrow ? 0.55 : 0.62, fy = narrow ? 0.6 : 0.56;
      const bx = 50 + (x - 50) * fx, by = 50 + (y - 50) * fy;
      html += `<div class="bet-spot" style="left:${bx}%;top:${by}%">${showBubble ? `<div class="bubble">${word}</div>` : ''}` +
        `${p.bet > 0 ? `<div class="bet-chip"><i></i>${fmt(p.bet)}</div>` : ''}</div>`;
    }
    if (p.dealer) {
      const dx = 50 + (x - 50) * 0.78 + (y > 50 ? 8 : -8) * (narrow ? 1.6 : 1), dy = 50 + (y - 50) * 0.78;
      html += `<div class="dealer-btn" style="left:${dx}%;top:${dy}%">D</div>`;
    }
  }
  $('seats').innerHTML = html;
}

function bubbleWord(a) {
  if (!a) return '';
  if (a === 'Check') return 'check';
  if (a.startsWith('Call')) return 'call';
  if (a.startsWith('Bet')) return 'bet';
  if (a.startsWith('Raise')) return 'raise';
  if (a.startsWith('All-in')) return 'all in';
  return '';
}

function cardRole(h, i) {
  if (h.sideIdx && h.sideIdx.includes(i)) return 'side-card';
  return h.use && h.use.includes(i) ? 'use-card' : 'unused';
}

// ---------- my cards and the showdown pick ----------

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
  texas: 'tap the cards you play — 2, 1 or 0 (0 = play the board)',
  omaha: 'tap exactly 2 of your 4 cards',
  '135': 'tap exactly 1, 3 or 5 of your cards',
  '999': 'from your other 2 cards, tap the ones you play for Texas (2, 1 or 0)',
  theenpathi: 'from your other 2 cards, tap the ones you play for Texas (2, 1 or 0)',
};

function pickMode(s, my) {
  const live = my.inHand && !my.folded && my.cards.length > 0 && s.phase !== 'handover';
  if (!live || my.declared) return null;
  if (s.split) return 'side';
  return s.phase === 'declare' ? 'use' : null;
}
function curSide(my) { return my.sideIdx || pendingSide; }
function curUse(s, my) { return s.phase === 'declare' ? (pendingUse || my.useIdx || []) : []; }

function myCardsHTML(s, my) {
  const h = s.phase === 'handover' && s.result && s.result.hands && s.result.hands[my.id];
  if (h) return my.cards.map((c, i) => cardHTML(c, h.mucked ? 'unused' : cardRole(h, i))).join('');
  const mode = pickMode(s, my), side = curSide(my), use = curUse(s, my);
  return my.cards.map((c, i) => cardHTML(c, [mode && 'pick', s.split && side.includes(i) && 'side-card',
    use.includes(i) && 'use-card', my.folded && 'dim'].filter(Boolean).join(' '), ` data-ci="${i}"`)).join('');
}

function onMyCard(i) {
  const s = state, my = me(); if (!s || !my) return;
  const mode = pickMode(s, my);
  if (mode === 'side') toggleSide(i);
  else if (mode === 'use') toggleUse(i);
}

function renderMine(s, my) {
  const info = $('pickInfo');
  const cards = my.cards || [];
  const live = my.inHand && !my.folded && cards.length > 0;
  const declaring = s.phase === 'declare' && live;
  const side = curSide(my);
  const use = curUse(s, my);
  const sideName = s.variant === '999' ? '999' : 'Theenpathi';
  if (declaring && pendingUse === null && !my.declared) {   // start the preview with nothing selected
    pendingUse = my.useIdx || [];
    send({ type: 'use', idx: pendingUse });
  }
  $('myHand').innerHTML = cards.length && !(my.folded && s.phase !== 'handover') ? myCardsHTML(s, my) : '';

  if (!live || s.phase === 'handover') { info.innerHTML = ''; return; }
  let html = '';
  if (s.split) {
    if (side.length === 3) {
      const sc = side.map((i) => cards[i]);
      html += `<div><b>${sideName}:</b> <span class="t">${sc.map(pretty).join(' ')} = ${s.variant === '999' ? value999(sc) : tpName(sc)}</span></div>`;
    } else {
      html += `<div>Select <b>3 cards</b> for your ${sideName} hand — the other 2 play Texas. (${3 - side.length} more)</div>`;
    }
    if (!declaring) html += '<div class="muted">You can change them until the showdown.</div>';
  }
  if (declaring && !my.declared) {
    const sideDone = !s.split || side.length === 3;
    if (s.split) html = `<div class="pstep">Showdown · Step 1 — your ${sideName} cards:</div>` + html;
    if (sideDone) {
      html += `<div class="pstep">${s.split ? 'Step 2 — ' : 'Showdown — '}${USE_RULE[s.variant]}.</div>`;
      if (s.split) {
        const rest = cards.map((c, i) => i).filter((i) => !side.includes(i));
        html += `<div class="use-row">${rest.map((i) => cardHTML(cards[i], `pick ${use.includes(i) ? 'use-card' : ''}`, ` data-ui="${i}"`)).join('')}</div>`;
      }
      html += previewHTML(s, cards, use);
    }
    const ok = s.preview && s.preview.desc && sideDone;
    html += `<div class="declare-row"><button id="declareBtn" class="btn green small" ${ok ? '' : 'disabled'}>Confirm my cards</button>` +
      ' <span class="count declare-count"></span> <span class="muted">No confirm = muck.</span></div>';
  } else if (declaring) {
    html += previewHTML(s, cards, use);
    html += '<div class="declare-row">✓ Confirmed — waiting for the others… <span class="count declare-count"></span></div>';
  }
  info.innerHTML = html;
  const b = $('declareBtn');
  if (b) b.onclick = () => send({ type: 'declare', use, side: s.split ? side : null });
}

function previewHTML(s, cards, use) {
  const pv = s.preview;
  if (!pv) return '';
  if (pv.error) return use.length ? `<div class="preview bad">${esc(pv.error)}</div>` : '<div class="preview muted">Tap the cards you are using.</div>';
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
  render();
}

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
  render();
}

// ---------- actions ----------

function renderActions(s, my) {
  const lg = s.legal, acts = $('actions'), pre = $('preActions'), msg = $('dockMsg'), rp = $('raisePanel');
  const turnKey = lg ? `${s.handNo}|${s.phase}|${lg.currentBet}|${lg.toCall}` : '';
  if (lg && turnKey !== lastTurnKey) sound.turn();
  lastTurnKey = turnKey;

  if (lg && preAction && autoSent !== turnKey) {
    const a = preAction;
    preAction = null;
    if (a === 'checkfold') { autoSent = turnKey; send({ type: 'act', action: lg.canCheck ? 'check' : 'fold' }); return hideActs(); }
    if (a === 'call') { autoSent = turnKey; send({ type: 'act', action: lg.canCheck ? 'check' : 'call' }); return hideActs(); }
    if (a === 'check' && lg.canCheck) { autoSent = turnKey; send({ type: 'act', action: 'check' }); return hideActs(); }
  }

  if (lg) {
    pre.classList.add('hidden');
    msg.innerHTML = turnTotal ? 'Your turn <span class="count turn-count"></span>' : 'Your turn';
    $('checkBtn').innerHTML = lg.canCheck ? 'CHECK' : (lg.toCall >= my.chips ? `ALL IN<small>${fmt(lg.toCall)}</small>` : `CALL<small>${fmt(lg.toCall)}</small>`);
    $('raiseBtn').textContent = lg.currentBet === 0 ? 'BET' : 'RAISE';
    $('raiseBtn').classList.toggle('hidden', !lg.canRaise);
    acts.classList.toggle('two', !lg.canRaise);
    if (!lg.canRaise) raiseOpen = false;
    acts.classList.toggle('hidden', raiseOpen);
    rp.classList.toggle('hidden', !raiseOpen);
    if (lg.canRaise) {
      const slider = $('raiseSlider'), input = $('raiseInput');
      slider.min = lg.minTo; slider.max = lg.maxTo; slider.step = 1;
      if (turnKey !== raiseKey) { raiseKey = turnKey; setRaise(lg.minTo); }
      else if (document.activeElement === input) onTyped();  // don't overwrite what's being typed
      else setRaise(+input.value);
    }
    return;
  }
  hideActs();
  // not my turn: pre-select an action, or explain what's happening
  const canPre = my.inHand && !my.folded && !my.allIn && STREETS.includes(s.phase) && !s.paused;
  pre.classList.toggle('hidden', !canPre);
  if (canPre) {
    const facing = Math.max(0, ...s.seats.map((p) => p.bet)) > my.bet;
    if (facing && preAction === 'check') preAction = null;
    pre.querySelector('[data-pre=check]').classList.toggle('hidden', facing);
    pre.querySelectorAll('.pre').forEach((b) => b.classList.toggle('on', b.dataset.pre === preAction));
  } else preAction = null;
  msg.innerHTML = dockMessage(s, my);
}
function hideActs() {
  $('actions').classList.add('hidden');
  $('raisePanel').classList.add('hidden');
}

function canShow(s, my) {
  // after a hand, cards that weren't revealed at showdown can be shown
  const h = s.result && s.result.hands && s.result.hands[my.id];
  return s.phase === 'handover' && my.cards.length > 0 && !my.shown && !(h && !h.mucked);
}

function dockMessage(s, my) {
  const turn = s.seats.find((p) => p.turn);
  if (s.paused) return '⏸ The host paused the game';
  if (my.seat === null) {
    if (my.seatRequest !== null) return `Waiting for the host to let you sit in seat ${my.seatRequest + 1}…`;
    return 'You are watching — tap an empty <b>SIT</b> seat to play.';
  }
  const parts = [];
  if (canShow(s, my)) {
    parts.push('<button class="btn small" data-do="show">SHOW CARDS</button>');
  }
  if (my.chips === 0 && !my.pendingCashout && !inLiveHand(s, my)) {
    parts.push(`You're out of chips <button class="btn green small" data-do="rebuy">BUY IN ${fmt(s.startingChips)}</button>`);
  }
  if (my.sittingOut) parts.push(`You're away <button class="btn small" data-do="back">I'M BACK</button>`);
  if (parts.length) return parts.join(' ');
  if (s.phase === 'choosing') return s.chooser === s.you ? 'Pick the game for this hand' : `${turn ? esc(turn.name) : 'Small blind'} is choosing the game…`;
  if (s.phase === 'declare') return my.inHand && !my.folded ? '' : 'Showdown — players are choosing their cards…';
  if (STREETS.includes(s.phase)) return turn ? `Waiting for ${esc(turn.name)}…` : '';
  if (s.phase === 'handover') return s.canStart ? 'Next hand starting…' : 'Waiting for players…';
  return '';
}

function clampRaise(v) {
  const lg = state.legal;
  return Math.max(lg.minTo, Math.min(lg.maxTo, Math.round(v) || lg.minTo));
}
function raiseLabel(v) {
  const lg = state.legal;
  return v === lg.maxTo ? `ALL IN<small>${fmt(v)}</small>` : `${lg.currentBet === 0 ? 'BET' : 'RAISE TO'}<small>${fmt(v)}</small>`;
}
function setRaise(v) {
  const lg = state.legal; if (!lg) return;
  v = clampRaise(v);
  $('raiseSlider').value = v; $('raiseInput').value = v;
  $('raiseConfirm').innerHTML = raiseLabel(v);
  $('raiseConfirm').disabled = false;
  const hint = $('raiseHint');
  hint.classList.remove('bad');
  hint.textContent = `Type any amount from ${lg.minTo} to ${lg.maxTo}`;
}
// Typing: keep the box exactly as typed, keep the slider and button in step
function onTyped() {
  const lg = state.legal; if (!lg) return;
  const input = $('raiseInput'), hint = $('raiseHint'), btn = $('raiseConfirm');
  const digits = input.value.replace(/\D/g, '');
  if (digits !== input.value) input.value = digits;
  const v = parseInt(digits, 10);
  hint.classList.remove('bad');
  if (!digits) {
    btn.disabled = true; btn.innerHTML = raiseLabel(lg.minTo);
    hint.textContent = `Type any amount from ${lg.minTo} to ${lg.maxTo}`;
  } else if (v < lg.minTo) {
    btn.disabled = true; btn.innerHTML = raiseLabel(lg.minTo);
    hint.classList.add('bad'); hint.textContent = `Minimum is ${lg.minTo}`;
  } else {
    const amt = Math.min(v, lg.maxTo);
    $('raiseSlider').value = amt;
    btn.disabled = false; btn.innerHTML = raiseLabel(amt);
    if (v > lg.maxTo) { hint.classList.add('bad'); hint.textContent = `You only have ${lg.maxTo} — that's all-in`; }
    else hint.textContent = 'Press Enter or the button to bet';
  }
}

// ---------- table centre ----------

function renderCenter(s, my) {
  const msg = $('tableMsg'), banner = $('winBanner'), lobby = $('lobbyBox');
  let m = '';
  if (s.paused) m = '⏸ Game paused by the host';
  else if (s.phase === 'choosing') {
    const c = s.seats.find((p) => p.id === s.chooser);
    m = s.chooser === s.you ? 'You are choosing the game' : `${esc(c ? c.name : 'Small blind')} is choosing the game…`;
  } else if (s.phase === 'declare') m = 'Showdown — choosing cards <span class="count declare-count"></span>';
  else if (s.phase === 'handover' && !s.result) m = 'Waiting for players…';
  msg.innerHTML = m;

  if (s.phase === 'handover' && s.result) {
    const lines = [];
    s.result.pots.forEach((p) => p.awards.forEach((a) => {
      if (a.why.startsWith('Uncalled')) return;
      lines.push(`<div><span class="w">${esc(a.name)}</span> wins ${fmt(a.amount)}${s.result.uncontested ? '' : ` — ${esc(a.why)}`}</div>`);
    }));
    banner.innerHTML = lines.join('') + (s.result.uncontested ? '' : '<button data-do="details">DETAILS</button>');
    banner.classList.remove('hidden');
  } else banner.classList.add('hidden');

  if (!s.started) {
    const n = seated(s).length;
    lobby.classList.remove('hidden');
    lobby.innerHTML = `<div>Invite friends with this code</div><div class="big-code">${esc(s.code)}</div>
      <button class="btn small" data-do="copy">Copy invite link</button>
      <div>${n} player${n === 1 ? '' : 's'} seated${my.seat === null ? ' · tap an empty <b>SIT</b> seat to play' : ''}</div>
      ${isHost(s) ? `<button class="btn green" data-do="start" ${s.canStart ? '' : 'disabled'}>${s.canStart ? 'START GAME' : 'Need 2 seated players'}</button>`
        : '<div class="muted">Waiting for the host to start…</div>'}`;
  } else lobby.classList.add('hidden');
}

function renderRequests(s) {
  const box = $('requests');
  const reqs = isHost(s) ? s.seats.filter((p) => p.seatRequest !== null && !p.kicked) : [];
  $('optionsDot').classList.toggle('hidden', !reqs.length);
  if (!reqs.length) { box.classList.add('hidden'); return; }
  box.classList.remove('hidden');
  box.innerHTML = reqs.map((p) => `<div class="req-row"><span><b>${esc(p.name)}</b> wants to sit in seat ${p.seatRequest + 1}</span>
    <button class="btn green tiny" data-ans="${esc(p.id)}" data-ok="1">Accept</button>
    <button class="btn tiny" data-ans="${esc(p.id)}" data-ok="0">Decline</button></div>`).join('');
}

function showdownHTML(s) {
  const r = s.result, won = {};
  r.pots.forEach((p) => p.awards.forEach((a) => (won[a.id] = (won[a.id] || 0) + a.amount)));
  let html = '<div class="sd-rows">';
  s.seats.filter((p) => r.hands[p.id]).sort((a, b) => (won[b.id] || 0) - (won[a.id] || 0)).forEach((p) => {
    const h = r.hands[p.id];
    const hole = p.cards.map((c, i) => cardHTML(c, h.mucked ? 'unused' : cardRole(h, i))).join('');
    let detail;
    if (h.mucked) detail = '<span class="muted">Mucked — didn\'t confirm in time</span>';
    else {
      const usedHole = h.use.map((i) => p.cards[i]);
      detail = `<b>${esc(h.main)}</b><div class="sd-made">` +
        `${usedHole.map((c) => cardHTML(c, 'use-card')).join('')}` +
        `${usedHole.length ? '<span class="plus">+</span>' : '<span class="muted">board only</span>'}` +
        `${h.board.map((c) => cardHTML(c)).join('')}</div>`;
      if (h.side) {
        const sc = h.sideIdx.map((i) => p.cards[i]);
        detail += `<div class="sd-side">${esc(r.sideName)}: ${sc.map((c) => cardHTML(c, 'side-card')).join('')} <b>${esc(h.side)}</b></div>`;
      }
    }
    html += `<div class="sd-row ${won[p.id] ? 'won' : ''}">
      <div class="sd-name">${won[p.id] ? '🏆 ' : ''}${esc(p.name)}${won[p.id] ? `<div class="sd-won">+${fmt(won[p.id])}</div>` : ''}</div>
      <div class="sd-hole">${hole}</div>
      <div class="sd-detail">${detail}</div></div>`;
  });
  html += '</div>';
  html += r.pots.map((p, i) => {
    const label = r.pots.length > 1 ? (i === 0 ? 'Main pot' : `Side pot ${i}`) : 'Pot';
    return `<div class="pot-line"><b>${label} (${fmt(p.amount)})</b>: ` +
      p.awards.map((a) => `${esc(a.name)} wins ${fmt(a.amount)} — ${esc(a.why)}`).join('; ') + '</div>';
  }).join('');
  html += '<div class="sd-key"><span class="k use"></span> cards used' + (r.sideName ? ` <span class="k side"></span> ${esc(r.sideName)} cards` : '') + '</div>';
  return html;
}

// ---------- chat ----------

function renderChat() {
  const c = $('chat');
  const atBottom = c.scrollTop + c.clientHeight >= c.scrollHeight - 20;
  c.innerHTML = chat.map((m) => `<div class="cm"><span class="n" style="color:${nameColor(m.id || m.name)}">${esc(m.name)}</span>` +
    `<span class="x">${esc(m.text)}</span>${m.t ? `<span class="tm">${fmtTime(m.t)}</span>` : ''}</div>`).join('') ||
    '<div class="cm sys"><span class="x">Chat with the table here.</span></div>';
  if (atBottom) c.scrollTop = c.scrollHeight;
  const open = $('chatBox').classList.contains('open');
  if (open) seenChat = chat.length;
  $('chatDot').classList.toggle('hidden', open || chat.length <= seenChat);
}

// ---------- options drawer ----------

function opt(label, sub, attrs, disabled, extra = '') {
  return `<button class="opt-btn ${extra}" ${attrs} ${disabled ? 'disabled' : ''}>${label}${sub ? `<small>${sub}</small>` : ''}</button>`;
}
function toggleRow(key, label, sub) {
  return `<label class="toggle"><span>${label}${sub ? `<small>${sub}</small>` : ''}</span><input type="checkbox" data-pref="${key}" ${prefs[key] ? 'checked' : ''}></label>`;
}

function renderDrawer(s, my, full) {
  const body = $('drawerBody');
  const keepSettings = !full && $('setBox') && $('setBox').dataset.dirty === '1';
  const oldSet = keepSettings ? $('setBox') : null;
  let html = '<h4>Your seat</h4>';
  if (my.seat !== null) {
    const live = inLiveHand(s, my);
    html += opt(`Buy in +${fmt(s.startingChips)}`, live ? 'Available when this hand is over' : `You've bought in ${my.buyins} time${my.buyins === 1 ? '' : 's'}`,
      'data-do="rebuy"', live || my.pendingCashout);
    html += opt(my.sittingOut ? "I'm back" : 'Away', my.sittingOut ? 'Deal me in again' : 'Keep your seat but skip the next hands', `data-do="${my.sittingOut ? 'back' : 'away'}"`);
    if (canShow(s, my)) html += opt('Show my cards', 'Reveal your last hand to the table', 'data-do="show"');
    html += opt(my.pendingCashout ? 'Leaving after this hand…' : 'Leave seat', `Cash out ${fmt(my.chips)} chips and watch`, 'data-do="leave"', my.pendingCashout, 'warn');
  } else if (my.seatRequest !== null) {
    html += opt('Cancel seat request', `Seat ${my.seatRequest + 1}, waiting for the host`, 'data-do="unsit"');
  } else {
    html += '<p class="muted">You are watching. Tap any empty <b>SIT</b> seat on the table to play.</p>';
  }
  html += '<h4>Game</h4>';
  html += opt('Log / Ledger', 'Every action, buy-ins and results', 'data-do="ledger"');
  html += opt('Rules', 'How each game works and what to choose', 'data-do="rules"');
  html += opt('Copy invite link', `Game code ${esc(s.code)}`, 'data-do="copy"');
  html += opt('Leave game', 'Go back to the home page', 'data-do="exit"');
  html += '<h4>Preferences</h4>';
  html += toggleRow('sound', 'Sounds', 'Your turn, cards, wins');
  html += toggleRow('fourColor', 'Four-colour deck', '♦ blue, ♣ green');
  html += toggleRow('bbUnits', 'Show amounts in big blinds');
  if (isHost(s)) {
    html += '<h4>Host</h4>';
    if (!s.started) html += opt('Start game', s.canStart ? '' : 'Needs 2 seated players with chips', 'data-do="start"', !s.canStart);
    else html += opt(s.paused ? 'Resume game' : 'Pause game', s.paused ? 'Timers continue' : 'Stops actions and timers', `data-do="${s.paused ? 'resume' : 'pause'}"`);
    html += '<div id="setSlot"></div>';
    html += '<h4>Players</h4>' + playersHTML(s);
  }
  body.innerHTML = html;
  if (isHost(s)) {
    const slot = $('setSlot');
    if (oldSet) slot.replaceWith(oldSet);
    else slot.outerHTML = settingsHTML(s);
  }
}

function settingsHTML(s) {
  const c = s.nextSettings || s.settings;
  const sel = (key, choices, fmtc) => `<select data-set="${key}">${choices.map((v) => `<option value="${v}" ${c[key] === v ? 'selected' : ''}>${fmtc(v)}</option>`).join('')}</select>`;
  return `<div id="setBox"><h4>Game settings</h4>
    <div class="settings-grid">
      <label>Small blind<input type="number" min="1" data-set="sb" value="${c.sb}"></label>
      <label>Big blind<input type="number" min="1" data-set="bb" value="${c.bb}"></label>
      <label>Ante<input type="number" min="0" data-set="ante" value="${c.ante}"></label>
      <label>Buy-in (chips)<input type="number" min="1" data-set="stack" value="${c.stack}"></label>
      <label>Turn time${sel('turn', [0, 15, 20, 30, 45, 60, 90, 120], (v) => (v ? `${v} s` : 'No limit'))}</label>
      <label>Showdown time${sel('declare', [30, 45, 60, 90, 120], (v) => `${v} s`)}</label>
    </div>
    <label class="toggle" style="margin-top:8px"><span>Approve who sits down<small>Off = anyone can take a seat</small></span><input type="checkbox" data-set="approval" ${c.approval ? 'checked' : ''}></label>
    ${s.nextSettings ? '<div class="settings-note">New settings start from the next hand.</div>' : ''}
    <button class="btn green small" data-do="saveSettings">Save settings</button></div>`;
}

function playersHTML(s) {
  const rows = s.seats.filter((p) => !p.kicked).map((p) => {
    const where = p.seat !== null ? `Seat ${p.seat + 1} · ${fmt(p.chips)} chips${p.sittingOut ? ' · away' : ''}`
      : p.seatRequest !== null ? `Wants seat ${p.seatRequest + 1}` : 'Watching';
    const btns = [];
    if (p.seatRequest !== null) btns.push(`<button class="btn green tiny" data-ans="${esc(p.id)}" data-ok="1">Accept</button><button class="btn tiny" data-ans="${esc(p.id)}" data-ok="0">Decline</button>`);
    if (p.id !== s.you) {
      if (p.connected) btns.push(`<button class="btn tiny" data-host="${esc(p.id)}">Make host</button>`);
      btns.push(`<button class="btn red tiny" data-kick="${esc(p.id)}">Remove</button>`);
    }
    return `<div class="prow"><div class="info"><b>${esc(p.name)}${p.id === s.you ? ' (you)' : ''}${p.id === s.hostId ? ' ★' : ''}</b>
      <span>${where}${p.connected ? '' : ' · offline'}</span></div>${btns.join('')}</div>`;
  });
  return rows.join('');
}

function openDrawer() { $('drawer').classList.remove('hidden'); if (state) renderDrawer(state, me(), true); }
function closeDrawer() { $('drawer').classList.add('hidden'); }

// ---------- ledger + log ----------

let ledgerSort = { key: 'net', dir: -1 };
const ledgerOpen = new Set();   // player ids whose details are expanded

function ledgerRows(s) {
  return s.seats.filter((p) => p.buyinTotal > 0 || p.history.length).map((p) => ({
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
      <td class="ldet"><button class="btn tiny" data-details="${esc(r.id)}">${ledgerOpen.has(r.id) ? 'Hide' : 'Details'}</button></td>
      <td>${r.buyin}</td><td>${r.buyout}</td><td>${r.stack}</td><td class="${cls}">${fmtNet(r.net)}</td></tr>`;
    if (ledgerOpen.has(r.id)) {
      html += `<tr class="ldetail"><td colspan="6"><div class="ldetail-box">
        <div class="muted">${r.buyins} buy-in${r.buyins === 1 ? '' : 's'} · ${r.history.filter((h) => h.kind === 'Buy-out').length} cash-out(s)</div>
        ${r.history.map((h) => `<div class="lev"><span>${fmtTime(h.t)}</span><span class="${h.kind === 'Buy-in' ? 'in' : 'out'}">${h.kind}</span><b>${h.amount}</b></div>`).join('')}
      </div></td></tr>`;
    }
    return html;
  }).join('') || '<tr><td class="l muted" colspan="6">Nobody has bought in yet.</td></tr>';
  const tot = rows.reduce((a, r) => ({ buyin: a.buyin + r.buyin, buyout: a.buyout + r.buyout, stack: a.stack + r.stack, net: a.net + r.net }),
    { buyin: 0, buyout: 0, stack: 0, net: 0 });
  $('ledgerFoot').innerHTML = `<tr><td class="l">Total</td><td class="ldet"></td><td>${tot.buyin}</td><td>${tot.buyout}</td><td>${tot.stack}</td><td>${fmtNet(tot.net)}</td></tr>`;
}

function renderFullLog(s) {
  const box = $('fullLog');
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
  box.innerHTML = s.log.map((l) => `<div class="${l.startsWith('---') ? 'hr' : ''}">${esc(l.replace(/^--- | ---$/g, ''))}</div>`).join('');
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function download(name, text, type) {
  const blob = new Blob([text], { type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function downloadLedger() {
  const rows = ledgerRows(state).sort((a, b) => b.net - a.net);
  const q = (v) => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [['Player', 'ID', 'Buy-ins (count)', 'Buy-in', 'Buy-out', 'Stack', 'Net'].map(q).join(',')];
  rows.forEach((r) => lines.push([r.name, r.id, r.buyins, r.buyin, r.buyout, r.stack, r.net].map(q).join(',')));
  lines.push('', ['Player', 'Time', 'Event', 'Amount'].map(q).join(','));
  rows.forEach((r) => r.history.forEach((h) => lines.push([r.name, new Date(h.t * 1000).toLocaleString(), h.kind, h.amount].map(q).join(','))));
  download(`poker-ledger-${state.code}-${new Date().toISOString().slice(0, 10)}.csv`, lines.join('\r\n'), 'text/csv');
}

function openLedger(tab) {
  const t = tab || 'ledger';
  document.querySelectorAll('#logTabs .tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === t));
  document.querySelectorAll('#ledger .tabpage').forEach((p) => p.classList.toggle('active', p.dataset.page === t));
  $('ledger').classList.remove('hidden');
  renderLedger(state); renderFullLog(state);
  if (t === 'log') $('fullLog').scrollTop = $('fullLog').scrollHeight;
}

function openRules(tab) {
  const want = tab || (state && state.variant) || 'general';
  document.querySelectorAll('.rtab').forEach((b) => b.classList.toggle('active', b.dataset.tab === want));
  document.querySelectorAll('.rpage').forEach((p) => p.classList.toggle('active', p.dataset.page === want));
  $('rules').classList.remove('hidden');
}

// ---------- timers ----------

function tick() {
  const tl = Math.max(0, (turnEnd - Date.now()) / 1000);
  document.querySelectorAll('.tbar').forEach((b) => {
    b.style.width = `${turnTotal ? Math.min(100, (tl / turnTotal) * 100) : 0}%`;
    b.classList.toggle('low', tl < 6);
  });
  document.querySelectorAll('.turn-count').forEach((el) => (el.textContent = turnEnd ? `${Math.ceil(tl)}s` : ''));
  const cc = $('chooseCount'); if (cc) cc.textContent = turnEnd ? `${Math.ceil(tl)}s left` : '';
  const dl = Math.max(0, Math.ceil((declareEnd - Date.now()) / 1000));
  document.querySelectorAll('.declare-count').forEach((el) => (el.textContent = declareEnd ? `${dl}s` : ''));
  document.querySelectorAll('.emote[data-ek]').forEach((el) => {
    if (Date.now() - (emoteSeen.get(el.dataset.ek) || 0) > 3200) el.remove();
  });
}
setInterval(tick, 250);

// phones: keep the table above the bottom panel
function fitDock() {
  const game = $('game');
  if (window.innerWidth <= 700) game.style.setProperty('--dock-h', `${$('dock').offsetHeight + 4}px`);
  else game.style.removeProperty('--dock-h');
}
if (window.ResizeObserver) new ResizeObserver(fitDock).observe($('dock'));

// ---------- wiring ----------

$('variantList').innerHTML = VARIANTS.map((v) => `<button class="variant" data-v="${v.key}"><h4>${v.name}</h4><p>${v.desc}</p></button>`).join('');
$('variantList').onclick = (e) => {
  const b = e.target.closest('[data-v]'); if (b) send({ type: 'choose', variant: b.dataset.v });
};

const nameInput = $('name');
try { nameInput.value = localStorage.getItem('poker.name') || ''; } catch {}
const urlCode = new URLSearchParams(location.search).get('code');
if (urlCode) $('joinCode').value = urlCode.toUpperCase();

function start(type) {
  const name = nameInput.value.trim();
  if (!name) { $('homeErr').textContent = 'Enter your nickname first'; nameInput.focus(); return; }
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
nameInput.onkeydown = (e) => { if (e.key === 'Enter') ($('joinCode').value.trim() ? start('join') : start('create')); };

function fold() {
  if (!state.legal) return;
  if (state.legal.canCheck && !confirm('You can check for free. Fold anyway?')) return;
  send({ type: 'act', action: 'fold' });
}
function checkCall() { if (state.legal) send({ type: 'act', action: state.legal.canCheck ? 'check' : 'call' }); }
function openRaise() { if (state.legal && state.legal.canRaise) { raiseOpen = true; render(); $('raiseInput').focus(); } }
function confirmRaise() {
  const v = parseInt($('raiseInput').value, 10);
  if (!state.legal || !(v >= state.legal.minTo)) return;
  raiseOpen = false;
  send({ type: 'act', action: 'raise', amount: clampRaise(v) });
}
$('foldBtn').onclick = fold;
$('checkBtn').onclick = checkCall;
$('raiseBtn').onclick = openRaise;
$('raiseBack').onclick = () => { raiseOpen = false; render(); };
$('raiseConfirm').onclick = confirmRaise;
$('raiseSlider').oninput = (e) => setRaise(+e.target.value);
$('raiseInput').oninput = onTyped;
$('raiseInput').onfocus = (e) => e.target.select();
$('raiseInput').onblur = (e) => { if (state && state.legal && parseInt(e.target.value, 10) >= state.legal.minTo) setRaise(+e.target.value); };
$('raiseInput').onkeydown = (e) => {
  if (e.key === 'Enter') { e.preventDefault(); confirmRaise(); }
  if (e.key === 'Escape') { raiseOpen = false; render(); }
};
$('raisePanel').onclick = (e) => {
  const lg = state && state.legal; if (!lg) return;
  const p = e.target.closest('[data-p]'), st = e.target.closest('[data-step]');
  if (p) {
    const after = state.pot + lg.toCall;
    setRaise({ min: lg.minTo, all: lg.maxTo, half: lg.currentBet + Math.floor(after / 2),
      threeq: lg.currentBet + Math.floor(after * 3 / 4), pot: lg.currentBet + after }[p.dataset.p]);
  } else if (st) setRaise((+$('raiseInput').value || lg.minTo) + (+st.dataset.step) * state.settings.bb);
};
$('preActions').onclick = (e) => {
  const b = e.target.closest('[data-pre]'); if (!b) return;
  preAction = preAction === b.dataset.pre ? null : b.dataset.pre;
  render();
};
document.addEventListener('keydown', (e) => {
  if (!state || !state.legal || e.target.matches('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'f') fold();
  else if (k === 'c' || k === 'k') checkCall();
  else if (k === 'r' || k === 'b') { e.preventDefault(); openRaise(); }
});

// table clicks: sit, my cards, banner buttons
$('zone').onclick = (e) => {
  const sit = e.target.closest('[data-sit]');
  if (sit) { send({ type: 'sit', seat: +sit.dataset.sit }); return; }
  if (e.target.closest('[data-unsit]')) { send({ type: 'unsit' }); return; }
  const c = e.target.closest('.seat.me .card[data-ci]');
  if (c) { onMyCard(+c.dataset.ci); return; }
  const d = e.target.closest('[data-do]');
  if (d) doAction(d.dataset.do);
};
$('myHand').onclick = (e) => { const c = e.target.closest('[data-ci]'); if (c) onMyCard(+c.dataset.ci); };
$('pickInfo').onclick = (e) => { const c = e.target.closest('[data-ui]'); if (c) toggleUse(+c.dataset.ui); };
$('dockMsg').onclick = (e) => { const d = e.target.closest('[data-do]'); if (d) doAction(d.dataset.do); };
$('requests').onclick = (e) => answerClick(e);

function answerClick(e) {
  const a = e.target.closest('[data-ans]');
  if (a) { send({ type: 'answer', id: a.dataset.ans, accept: a.dataset.ok === '1' }); return true; }
  return false;
}

async function copyInvite() {
  const link = `${location.origin}/?code=${state.code}`;
  try { await navigator.clipboard.writeText(link); toast('Invite link copied', true); }
  catch { prompt('Invite link', link); }
}

function doAction(what) {
  const s = state, my = me(); if (!s || !my) return;
  switch (what) {
    case 'start': send({ type: 'start' }); break;
    case 'copy': copyInvite(); break;
    case 'details': $('sdBody').innerHTML = showdownHTML(s); $('sdModal').classList.remove('hidden'); break;
    case 'show': send({ type: 'show' }); break;
    case 'rebuy':
      if (confirm(`Buy in for another ${s.startingChips} chips?`)) send({ type: 'rebuy' });
      break;
    case 'away': send({ type: 'sitout', value: true }); break;
    case 'back': send({ type: 'sitout', value: false }); break;
    case 'leave': {
      const live = inLiveHand(s, my) && !my.folded;
      if (confirm(`Leave your seat and cash out ${my.chips} chips?` + (live ? ' You are in a hand, so you leave when it ends.' : '') + ' You can sit down again later.')) send({ type: 'cashout' });
      break;
    }
    case 'unsit': send({ type: 'unsit' }); break;
    case 'ledger': closeDrawer(); openLedger('ledger'); break;
    case 'rules': closeDrawer(); openRules(); break;
    case 'exit':
      if (confirm(my.seat !== null ? 'Leave the game? Your seat and chips stay at the table (use Leave seat first to cash out).' : 'Leave the game?')) leaveTable('');
      break;
    case 'pause': send({ type: 'pause', value: true }); break;
    case 'resume': send({ type: 'pause', value: false }); break;
    case 'saveSettings': {
      const box = $('setBox'), out = {};
      box.querySelectorAll('[data-set]').forEach((el) => {
        out[el.dataset.set] = el.type === 'checkbox' ? el.checked : +el.value;
      });
      send({ type: 'settings', settings: out });
      box.dataset.dirty = '';
      setTimeout(() => state && !$('drawer').classList.contains('hidden') && renderDrawer(state, me(), true), 300);
      toast('Settings saved', true);
      break;
    }
  }
}

$('optionsBtn').onclick = openDrawer;
$('drawerClose').onclick = closeDrawer;
$('drawer').onclick = (e) => {
  if (e.target.id === 'drawer') { closeDrawer(); return; }
  if (answerClick(e)) return;
  const k = e.target.closest('[data-kick]');
  if (k) {
    const p = state.seats.find((x) => x.id === k.dataset.kick); if (!p) return;
    const live = p.inHand && !p.folded && ACTIVE.includes(state.phase);
    if (confirm(`Remove ${p.name} from the game?` + (live ? ' They will fold this hand.' : '') +
      (p.seat !== null ? ` Their ${p.chips} chips will be cashed out in the ledger.` : '') + " They won't be able to rejoin.")) send({ type: 'kick', id: p.id });
    return;
  }
  const h = e.target.closest('[data-host]');
  if (h) {
    const p = state.seats.find((x) => x.id === h.dataset.host);
    if (p && confirm(`Make ${p.name} the host? You'll lose the host controls.`)) send({ type: 'makehost', id: p.id });
    return;
  }
  const d = e.target.closest('[data-do]');
  if (d) doAction(d.dataset.do);
};
$('drawer').addEventListener('input', (e) => {
  if (e.target.closest('#setBox')) $('setBox').dataset.dirty = '1';
  const p = e.target.dataset.pref;
  if (p) { prefs[p] = e.target.checked; savePrefs(); }
});
$('drawer').addEventListener('change', (e) => { if (e.target.closest('#setBox')) $('setBox').dataset.dirty = '1'; });

$('soundBtn').onclick = () => { prefs.sound = !prefs.sound; savePrefs(); if (prefs.sound) sound.deal(); };
$('codeChip').onclick = copyInvite;
$('logBtn').onclick = () => openLedger('ledger');
$('logTabs').onclick = (e) => { const t = e.target.dataset.tab; if (t) openLedger(t); };
$('ledgerDownload').onclick = downloadLedger;
$('logDownload').onclick = () => download(`poker-log-${state.code}.txt`, state.log.join('\n'), 'text/plain');
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
document.querySelectorAll('[data-close]').forEach((b) => (b.onclick = () => $(b.dataset.close).classList.add('hidden')));
['ledger', 'rules', 'sdModal'].forEach((id) => $(id).addEventListener('click', (e) => { if (e.target.id === id) $(id).classList.add('hidden'); }));
document.querySelectorAll('.rules-link').forEach((l) => (l.onclick = (e) => { e.preventDefault(); openRules('general'); }));
document.querySelector('.rules-tabs').onclick = (e) => { const t = e.target.dataset.tab; if (t) openRules(t); };

// chat + reactions
$('chatForm').onsubmit = (e) => {
  e.preventDefault();
  const t = $('chatInput').value.trim(); if (t) send({ type: 'chat', text: t });
  $('chatInput').value = '';
};
$('emoteBtn').onclick = (e) => {
  e.stopPropagation();
  const box = $('emotes');
  if (state) box.innerHTML = state.emotes.map((x) => `<button type="button" data-e="${x}">${x}</button>`).join('');
  box.classList.toggle('hidden');
};
$('emotes').onclick = (e) => {
  const b = e.target.closest('[data-e]'); if (!b) return;
  const my = me();
  if (my && my.seat !== null) send({ type: 'emote', e: b.dataset.e });
  else send({ type: 'chat', text: b.dataset.e });
  $('emotes').classList.add('hidden');
};
document.addEventListener('click', (e) => { if (!e.target.closest('#emotes, #emoteBtn')) $('emotes').classList.add('hidden'); });
$('chatToggle').onclick = () => { $('chatBox').classList.toggle('open'); renderChat(); $('chat').scrollTop = $('chat').scrollHeight; };
$('chatClose').onclick = () => $('chatBox').classList.remove('open');

window.addEventListener('resize', () => { if (state) render(); });

applyPrefs();
// Resume a seat after a refresh if this browser was already at a table
if (session && (!urlCode || urlCode.toUpperCase() === session.code)) { show('game'); connect(); }
else show('home');
