"""Table state and rules: seats, blinds, betting rounds, side pots and split-pot showdowns."""
import random
import secrets
import time

from itertools import combinations

import evaluator as ev

STARTING_CHIPS = 200   # default stack for a buy-in (the host can change it)
MAX_SEATS = 8          # 5-card games need 5 cards each + board + burns from one deck
DEFAULT_SETTINGS = {
    'sb': 1, 'bb': 2, 'ante': 0, 'stack': STARTING_CHIPS,
    'turn': 30,          # seconds per decision (0 = no limit)
    'declare': 60,       # seconds to choose your cards at showdown (no choice = muck)
    'approval': True,    # the host approves who sits down
}
TURN_CHOICES = (0, 15, 20, 30, 45, 60, 90, 120)
DECLARE_CHOICES = (30, 45, 60, 90, 120)
HOST_GRACE = 60       # seconds a disconnected host keeps the host role
EMOTES = ('👍', '😂', '😮', '😡', '😭', '🔥', '🙏', '😎', '🤡', '💰')

VARIANTS = {
    'texas': {'name': "Texas Hold'em", 'hole': 2, 'split': False},
    '999': {'name': '999', 'hole': 5, 'split': True},
    '135': {'name': '1 3 5', 'hole': 5, 'split': False},
    'theenpathi': {'name': 'Theenpathi', 'hole': 5, 'split': True},
    'omaha': {'name': 'Omaha', 'hole': 4, 'split': False},
}
SIDE_GAME_NAME = {'999': '999', 'theenpathi': 'Theenpathi'}
STREETS = ['preflop', 'flop', 'turn', 'river']
ACTIVE = STREETS + ['choosing', 'declare']   # a hand is being played


def new_deck():
    deck = [r + s for r in ev.RANKS for s in 'shdc']
    random.SystemRandom().shuffle(deck)
    return deck


class Player:
    def __init__(self, name):
        self.id = secrets.token_hex(4)
        self.token = secrets.token_urlsafe(16)  # secret used to reconnect
        self.name = name
        self.seat = None          # seat number 0..MAX_SEATS-1, None = watching
        self.seat_request = None  # seat asked for, waiting for the host
        self.chips = 0
        self.buyins = 0
        self.buyout = 0           # chips taken off the table by leaving
        self.pending_cashout = False
        self.kicked = False       # removed by the host: can't rejoin, kept in the ledger
        self.history = []         # [{t, kind: 'Buy-in' | 'Buy-out', amount}]
        self.hands_won = 0
        self.connected = True
        self.left_at = 0          # when they disconnected
        self.sitting_out = False
        self.emote = None
        self.emote_t = 0
        self.reset_hand()

    def reset_hand(self):
        self.in_hand = False
        self.hole = []
        self.folded = False
        self.all_in = False
        self.bet = 0          # chips put in on the current street
        self.total_bet = 0    # chips put in this hand
        self.acted = False
        self.side_idx = None  # indices of the 3 hole cards used for 999 / Theenpathi
        self.declared = False # confirmed their final pick at showdown
        self.use_idx = None   # hole cards chosen for the poker hand at showdown
        self.shown = False    # chose to show their cards after the hand
        self.last_action = ''

    @property
    def active(self):
        """Still able to make betting decisions."""
        return self.in_hand and not self.folded and not self.all_in

    @property
    def buyin_total(self):
        return sum(h['amount'] for h in self.history if h['kind'] == 'Buy-in')


class Game:
    def __init__(self, code):
        self.code = code
        self.members = []        # everyone who joined: seated players and watchers
        self.players = []        # the hand's roster in seat order (rebuilt when a hand starts)
        self.host_id = None
        self.started = False
        self.phase = 'lobby'     # lobby | choosing | preflop | flop | turn | river | declare | handover
        self.settings = dict(DEFAULT_SETTINGS)
        self.next_settings = None  # changed mid-hand: used from the next hand
        self.paused = False
        self.paused_at = 0
        self.dealer = -1
        self.dealer_seat = -1
        self.sb = self.bb = -1
        self.to_act = -1
        self.turn_deadline = 0
        self.variant = None
        self.board = []
        self.deck = []
        self.current_bet = 0
        self.min_raise = self.settings['bb']
        self.hand_no = 0
        self.result = None       # summary of the last finished hand
        self.declare_deadline = 0
        self.log = []

    # ----- members and seats -----

    def add_member(self, name):
        p = Player(name)
        self.members.append(p)
        if self.host_id is None:
            self.host_id = p.id
        self.note(f'{name} joined')
        return p

    def add_player(self, name):
        """Join and sit straight down in the next free seat (used by tests and bots)."""
        p = self.add_member(name)
        self._sit(p, min(self.free_seats()))
        return p

    def find(self, pid):
        return next((p for p in self.members if p.id == pid), None)

    def seated(self):
        return sorted((p for p in self.members if p.seat is not None), key=lambda p: p.seat)

    def free_seats(self):
        used = {p.seat for p in self.members if p.seat is not None}
        used |= {p.seat_request for p in self.members if p.seat_request is not None}
        return [s for s in range(MAX_SEATS) if s not in used]

    def is_host(self, p):
        return p is not None and p.id == self.host_id

    def _need_host(self, p, what):
        if not self.is_host(p):
            raise ValueError(f'Only the host can {what}')

    def ensure_host(self):
        """Hand the game to someone else only if the host was removed or has been gone a while."""
        host = self.find(self.host_id)
        gone = host is None or host.kicked or (not host.connected and time.time() - host.left_at > HOST_GRACE)
        if gone:
            live = [p for p in self.members if p.connected and not p.kicked]
            nxt = next((p for p in live if p.seat is not None), None) or (live[0] if live else None)
            if nxt:
                self.host_id = nxt.id

    def note(self, msg):
        self.log.append(msg)
        self.log = self.log[-300:]

    def request_seat(self, p, seat):
        """Ask to sit in a seat. The host (or anyone, when approval is off) sits straight away."""
        if p.kicked:
            raise ValueError('The host removed you from this game')
        if p.seat is not None:
            raise ValueError('You already have a seat')
        seat = int(seat)
        if not 0 <= seat < MAX_SEATS:
            raise ValueError('No such seat')
        if p.seat_request is not None:
            p.seat_request = None               # moving the request to another seat
        if seat not in self.free_seats():
            raise ValueError('That seat is taken')
        if self.is_host(p) or not self.settings['approval']:
            self._sit(p, seat)
        else:
            p.seat_request = seat
            self.note(f'{p.name} asked to sit in seat {seat + 1}')

    def cancel_request(self, p):
        p.seat_request = None

    def answer_request(self, host, p, accept):
        self._need_host(host, 'approve players')
        if p is None or p.seat_request is None:
            raise ValueError('That request is gone')
        seat, p.seat_request = p.seat_request, None
        if not accept:
            self.note(f'The host declined {p.name}')
            return
        if seat not in self.free_seats():
            raise ValueError('That seat is taken now')
        self._sit(p, seat)

    def _sit(self, p, seat):
        p.seat = seat
        p.seat_request = None
        p.sitting_out = False
        if p.chips == 0:
            self._add_buyin(p)
        self.note(f'{p.name} sat in seat {seat + 1} with {p.chips}')

    def _in_live_hand(self, p):
        return p.in_hand and self.phase in ACTIVE and p in self.players

    def rebuy(self, p):
        """Add a stack. Allowed any time you're seated, except while you're dealt into a hand."""
        if p.kicked:
            raise ValueError('The host removed you from this game')
        if p.seat is None:
            raise ValueError('Take a seat first')
        if p.pending_cashout:
            raise ValueError('You are leaving the table after this hand')
        if self._in_live_hand(p):
            raise ValueError('You can buy in once this hand is over')
        self._add_buyin(p)
        self.note(f'{p.name} bought in for {self.settings["stack"]} (buy-in #{p.buyins})')

    def _add_buyin(self, p):
        amount = self.settings['stack']
        p.chips += amount
        p.buyins += 1
        p.history.append({'t': time.time(), 'kind': 'Buy-in', 'amount': amount})

    def cash_out(self, p):
        """Leave your seat with your stack (recorded as a buy-out); mid-hand it happens when the hand ends."""
        if p.seat is None:
            raise ValueError('You are not seated')
        if p.pending_cashout:
            raise ValueError('You are already leaving after this hand')
        if self._in_live_hand(p) and not p.folded:
            p.pending_cashout = True
            self.note(f'{p.name} will leave the table after this hand')
        else:
            self._do_cashout(p)

    def _do_cashout(self, p):
        amount = p.chips
        p.buyout += amount
        p.chips = 0
        p.seat = None
        p.sitting_out = False
        p.pending_cashout = False
        p.history.append({'t': time.time(), 'kind': 'Buy-out', 'amount': amount})
        self.note(f'{p.name} left the table with {amount}')

    def kick(self, host, p):
        """Host removes someone: they fold if in a hand, their stack is cashed out, and they can't rejoin."""
        self._need_host(host, 'remove players')
        if p is None or p.kicked:
            raise ValueError('That player is not here')
        if p is host:
            raise ValueError("You can't remove yourself")
        if self.phase == 'choosing' and self.players[self.sb] is p:
            self.choose_variant(p, 'texas', force=True)   # the game can't wait for their pick
        p.kicked = True
        p.connected = False
        p.seat_request = None
        if self._in_live_hand(p) and not p.folded:
            p.folded = True
            p.last_action = 'Removed'
            if self.phase in STREETS and self.to_act >= 0 and self.players[self.to_act] is p:
                self._after_action()              # it was their turn: move on
            elif len(self.contenders()) == 1:
                self._win_uncontested(self.contenders()[0])
            elif self.phase == 'declare' and all(q.declared for q in self.contenders()):
                self._showdown()
        if p.seat is not None:
            p.pending_cashout = False
            self._do_cashout(p)
        self.note(f'{p.name} was removed by the host')

    def make_host(self, host, p):
        self._need_host(host, 'hand over the game')
        if p is None or p.kicked or not p.connected:
            raise ValueError('That player is not here')
        self.host_id = p.id
        self.note(f'{p.name} is now the host')

    def set_sitout(self, p, value):
        if p.seat is None:
            raise ValueError('You are not seated')
        p.sitting_out = bool(value)
        self.note(f'{p.name} is {"away" if p.sitting_out else "back"}')

    def emote_at(self, p, e):
        if e not in EMOTES:
            raise ValueError('Unknown reaction')
        p.emote, p.emote_t = e, time.time()

    def show_cards(self, p):
        if self.phase != 'handover' or p not in self.players or not p.hole:
            raise ValueError('Nothing to show')
        p.shown = True
        self.note(f'{p.name} shows {" ".join(p.hole)}')

    # ----- host settings and pause -----

    def update_settings(self, host, data):
        self._need_host(host, 'change the settings')
        cur = dict(self.next_settings or self.settings)

        def num(key, lo, hi):
            if key in data:
                v = int(data[key])
                if not lo <= v <= hi:
                    raise ValueError(f'{key} must be between {lo} and {hi}')
                cur[key] = v
        num('sb', 1, 10_000)
        num('bb', 1, 20_000)
        num('ante', 0, 10_000)
        num('stack', 1, 1_000_000)
        if 'turn' in data:
            if int(data['turn']) not in TURN_CHOICES:
                raise ValueError('Pick a turn time from the list')
            cur['turn'] = int(data['turn'])
        if 'declare' in data:
            if int(data['declare']) not in DECLARE_CHOICES:
                raise ValueError('Pick a showdown time from the list')
            cur['declare'] = int(data['declare'])
        if 'approval' in data:
            cur['approval'] = bool(data['approval'])
        if cur['bb'] < cur['sb']:
            raise ValueError('The big blind must be at least the small blind')
        if cur['stack'] < cur['bb']:
            raise ValueError('The buy-in must be at least the big blind')
        if self.phase in ACTIVE:
            self.next_settings = cur
            self.settings['approval'] = cur['approval']   # seating rules apply at once
            self.note('Host changed the settings (from the next hand)')
        else:
            self.settings, self.next_settings = cur, None
            self.note('Host changed the settings')

    def set_paused(self, host, value):
        self._need_host(host, 'pause the game')
        now = time.time()
        if value and not self.paused:
            self.paused, self.paused_at = True, now
            self.note('Game paused by the host')
        elif not value and self.paused:
            gap = now - self.paused_at
            if self.turn_deadline:
                self.turn_deadline += gap
            if self.declare_deadline:
                self.declare_deadline += gap
            self.paused = False
            self.note('Game resumed')

    # ----- seat helpers -----

    def next_seat(self, i, cond):
        n = len(self.players)
        for k in range(1, n + 1):
            j = (i + k) % n
            if cond(self.players[j]):
                return j
        return -1

    def in_hand_players(self):
        return [p for p in self.players if p.in_hand]

    def contenders(self):
        return [p for p in self.players if p.in_hand and not p.folded]

    def _ready(self, p):
        return (p.seat is not None and p.chips > 0 and p.connected and not p.sitting_out
                and not p.kicked and not p.pending_cashout)

    # ----- hand flow -----

    def can_start_hand(self):
        return sum(1 for p in self.members if self._ready(p)) >= 2

    def start_hand(self):
        if self.next_settings:
            self.settings, self.next_settings = self.next_settings, None
        if self.paused or not self.can_start_hand():
            self.phase = 'lobby' if not self.started else 'handover'
            return False
        self.started = True
        self.hand_no += 1
        self.result = None
        self.board = []
        self.variant = None
        for p in self.members:
            p.reset_hand()
        self.players = self.seated()
        for p in self.players:
            p.in_hand = self._ready(p)
        live = self.in_hand_players()
        # the button moves to the next seated player clockwise
        nxt = next((p for p in live if p.seat > self.dealer_seat), live[0])
        self.dealer = self.players.index(nxt)
        self.dealer_seat = nxt.seat
        eligible = lambda p: p.in_hand
        if len(live) == 2:  # heads-up: dealer posts the small blind
            self.sb = self.dealer
        else:
            self.sb = self.next_seat(self.dealer, eligible)
        self.bb = self.next_seat(self.sb, eligible)
        self.phase = 'choosing'
        self.to_act = self.sb
        self._new_turn()
        self.note(f'--- Hand #{self.hand_no}: {self.players[self.sb].name} (small blind) is choosing the game ---')
        return True

    def _new_turn(self):
        t = self.settings['turn']
        self.turn_deadline = time.time() + t if t else 0

    def choose_variant(self, p, variant, force=False):
        if self.phase != 'choosing' or self.players[self.sb] is not p:
            raise ValueError('Only the small blind can choose the game right now')
        if self.paused and not force:
            raise ValueError('The game is paused')
        if variant not in VARIANTS:
            raise ValueError('Unknown variant')
        self.variant = variant
        self.note(f'{p.name} chose {VARIANTS[variant]["name"]}')
        self.deck = new_deck()
        n_hole = VARIANTS[variant]['hole']
        for pl in self.in_hand_players():
            pl.hole = [self.deck.pop() for _ in range(n_hole)]
        ante = self.settings['ante']
        if ante:
            for pl in self.in_hand_players():
                a = min(ante, pl.chips)
                pl.chips -= a
                pl.total_bet += a
                if pl.chips == 0:
                    pl.all_in = True
        sb_amt, bb_amt = self.settings['sb'], self.settings['bb']
        self._post(self.players[self.sb], sb_amt, 'SB')
        self._post(self.players[self.bb], bb_amt, 'BB')
        self.current_bet = bb_amt
        self.min_raise = bb_amt
        self.phase = 'preflop'
        self.to_act = self.bb  # action starts left of the big blind
        self._after_action()

    def _post(self, p, amount, label):
        amt = min(amount, p.chips)
        self._put(p, amt)
        p.last_action = f'{label} {amt}'

    def _put(self, p, amt):
        p.chips -= amt
        p.bet += amt
        p.total_bet += amt
        if p.chips == 0:
            p.all_in = True

    def pot_total(self):
        return sum(p.total_bet for p in self.players)

    def legal(self, p):
        """What the player may do now (used by both the server checks and the UI)."""
        if self.paused or self.phase not in STREETS or self.to_act < 0 or self.players[self.to_act] is not p:
            return None
        bb = self.settings['bb']
        to_call = min(self.current_bet - p.bet, p.chips)
        max_to = p.bet + p.chips  # raise "to" amount when going all-in
        min_to = min(self.current_bet + self.min_raise if self.current_bet else bb, max_to)
        can_raise = max_to > self.current_bet and any(
            q.active and q is not p for q in self.players)
        return {'toCall': to_call, 'canCheck': to_call == 0, 'canRaise': can_raise,
                'minTo': min_to, 'maxTo': max_to, 'currentBet': self.current_bet}

    def act(self, p, action, amount=0):
        if self.paused:
            raise ValueError('The game is paused')
        lg = self.legal(p)
        if lg is None:
            raise ValueError('It is not your turn')
        if action == 'fold':
            p.folded = True
            p.last_action = 'Fold'
        elif action == 'check':
            if not lg['canCheck']:
                raise ValueError('You cannot check, there is a bet')
            p.last_action = 'Check'
        elif action == 'call':
            amt = lg['toCall']
            self._put(p, amt)
            p.last_action = 'All-in' if p.all_in else f'Call {amt}'
        elif action == 'raise':
            if not lg['canRaise']:
                raise ValueError('You cannot raise')
            to = int(amount)
            to = max(lg['minTo'], min(to, lg['maxTo']))
            raise_by = to - self.current_bet
            self._put(p, to - p.bet)
            if raise_by >= self.min_raise:
                self.min_raise = raise_by
            word = 'Bet' if self.current_bet == 0 else 'Raise to'
            self.current_bet = max(self.current_bet, to)
            p.last_action = f'All-in {to}' if p.all_in else f'{word} {to}'
            for q in self.players:
                if q is not p and q.active:
                    q.acted = False
        else:
            raise ValueError('Unknown action')
        p.acted = True
        self.note(f'{p.name}: {p.last_action}')
        self._after_action()

    def _needs_action(self, q):
        return q.active and (not q.acted or q.bet < self.current_bet)

    def _after_action(self):
        """self.to_act is the seat that just acted (or the seat before the first actor)."""
        live = self.contenders()
        if len(live) == 1:
            self._win_uncontested(live[0])
            return
        active = [q for q in self.players if q.active]
        lone_matched = len(active) == 1 and active[0].bet >= self.current_bet
        if not lone_matched and any(self._needs_action(q) for q in active):
            self.to_act = self.next_seat(self.to_act, self._needs_action)
            self._new_turn()
            return
        # betting round complete
        if sum(1 for q in live if not q.all_in) <= 1:
            while len(self.board) < 5:
                self._deal_street()
            self._reach_showdown()
            return
        if self.phase == 'river':
            self._reach_showdown()
            return
        self._deal_street()
        self.to_act = self.dealer  # action starts left of the dealer
        self._after_action()

    def _deal_street(self):
        for q in self.players:
            q.bet = 0
            q.acted = False
            if q.in_hand and not q.folded and not q.all_in:
                q.last_action = ''
        self.current_bet = 0
        self.min_raise = self.settings['bb']
        n = 3 if not self.board else 1
        self.deck.pop()  # burn
        self.board += [self.deck.pop() for _ in range(n)]
        self.phase = STREETS[min(STREETS.index(self.phase) + 1, 3)] if self.phase in STREETS else 'flop'
        self.note(f'{self.phase.capitalize()}: {" ".join(self.board)}')

    # ----- endings -----

    def _finish(self, result):
        self.result = result
        winners = {a['id'] for pot in result['pots'] for a in pot['awards']
                   if not a['why'].startswith('Uncalled')}
        for q in self.players:
            if q.id in winners:
                q.hands_won += 1
        for q in self.players:
            if q.pending_cashout:
                self._do_cashout(q)
        self.phase = 'handover'
        self.to_act = -1
        self.turn_deadline = 0
        self.declare_deadline = 0
        for q in self.players:
            q.bet = 0

    def _win_uncontested(self, w):
        pot = self.pot_total()
        w.chips += pot
        self.note(f'{w.name} wins {pot} (everyone else folded)')
        self._finish({'uncontested': True, 'pots': [{'amount': pot, 'awards': [
            {'id': w.id, 'name': w.name, 'amount': pot, 'why': 'Everyone else folded'}]}],
            'hands': {}})

    # ----- showdown: each player picks which of their own cards they use -----

    def allowed_counts(self):
        """How many hole cards may go into the poker hand (for split games: of the 2 non-side cards)."""
        return {'texas': (0, 1, 2), 'omaha': (2,), '135': (1, 3, 5),
                '999': (0, 1, 2), 'theenpathi': (0, 1, 2)}[self.variant]

    def _reach_showdown(self):
        """Pause with the full board out so everyone picks the cards they play."""
        self.phase = 'declare'
        self.to_act = -1
        self.declare_deadline = time.time() + self.settings['declare']
        for q in self.players:
            q.bet = 0
        self.note('Showdown: choose the cards you are playing')

    def set_split(self, p, idx):
        if not VARIANTS.get(self.variant, {}).get('split') or not p.in_hand or p.folded:
            raise ValueError('This game has no card split')
        if self.phase not in STREETS + ['declare'] or p.declared:
            raise ValueError('Your pick is final')
        idx = sorted(set(int(i) for i in idx))
        if len(idx) != 3 or any(i < 0 or i >= len(p.hole) for i in idx):
            raise ValueError('Pick exactly 3 cards')
        if p.use_idx and set(p.use_idx) & set(idx):
            p.use_idx = [i for i in p.use_idx if i not in idx]
        p.side_idx = idx

    def _check_use(self, p, use):
        """Returns an error message, or None if these hole cards are a legal choice."""
        if VARIANTS[self.variant]['split']:
            name = SIDE_GAME_NAME[self.variant]
            if p.side_idx is None:
                return f'First pick your 3 {name} cards'
            if set(use) & set(p.side_idx):
                return f'Those cards are in your {name} hand'
        if len(use) not in self.allowed_counts():
            words = {'omaha': 'exactly 2', '135': '1, 3 or 5'}.get(self.variant, '0, 1 or 2')
            return f'Use {words} of your cards'
        return None

    def set_use(self, p, idx):
        """Draft pick during the showdown (shown back as a preview only to that player)."""
        if self.phase != 'declare' or not p.in_hand or p.folded:
            raise ValueError('You choose your cards at showdown')
        if p.declared:
            raise ValueError('Your pick is final')
        idx = sorted(set(int(i) for i in idx))
        if any(i < 0 or i >= len(p.hole) for i in idx):
            raise ValueError('Bad card')
        p.use_idx = idx

    def declare(self, p, use, side=None):
        if self.phase != 'declare' or not p.in_hand or p.folded:
            raise ValueError('You confirm your cards at showdown')
        if p.declared:
            raise ValueError('Your pick is final')
        if VARIANTS[self.variant]['split']:
            if side is None:
                raise ValueError(f'Pick your 3 {SIDE_GAME_NAME[self.variant]} cards')
            self.set_split(p, side)
        self.set_use(p, use)
        err = self._check_use(p, p.use_idx)
        if err:
            raise ValueError(err)
        p.declared = True
        self.note(f'{p.name} is ready')
        if all(q.declared for q in self.contenders()):
            self._showdown()

    def finish_declare(self):
        """Time's up: players who didn't confirm muck their hand."""
        if self.phase == 'declare':
            self._showdown()

    def _hand_with(self, hole_cards):
        """Best 5-card hand using exactly these hole cards, completed from the board."""
        best = None
        for b in combinations(self.board, 5 - len(hole_cards)):
            score, desc = ev.eval5(list(hole_cards) + list(b))
            if best is None or score > best[0]:
                best = (score, desc, list(b))
        return best

    def preview(self, p):
        if self.phase != 'declare' or not p.in_hand or p.folded or p.use_idx is None:
            return None
        err = self._check_use(p, p.use_idx)
        if err:
            return {'error': err}
        score, desc, board_used = self._hand_with([p.hole[i] for i in p.use_idx])
        return {'desc': desc, 'board': board_used}

    def _evaluate(self, p, auto=False):
        """auto=True finds the best hand (only used when nobody in a pot confirmed)."""
        v = self.variant
        split = VARIANTS[v]['split']
        side_idx = p.side_idx
        if split and auto and side_idx is None:
            side_idx = list(ev.best_999_split(p.hole) if v == '999' else ev.best_tp_split(p.hole))
        avail = [i for i in range(len(p.hole)) if not split or i not in side_idx]
        if auto:
            best = None
            for k in self.allowed_counts():
                for use in combinations(avail, k):
                    score, desc, board_used = self._hand_with([p.hole[i] for i in use])
                    if best is None or score > best[0]:
                        best = (score, desc, board_used, list(use))
            score, desc, board_used, use = best
        else:
            use = p.use_idx
            score, desc, board_used = self._hand_with([p.hole[i] for i in use])
        out = {'main': (score, desc), 'use': list(use), 'board': board_used}
        if split:
            side_cards = [p.hole[i] for i in side_idx]
            out['side'] = ev.eval_999(side_cards) if v == '999' else ev.eval_tp(side_cards)
            out['sideIdx'] = list(side_idx)
        return out

    def _build_pots(self):
        levels = sorted({p.total_bet for p in self.players if p.total_bet > 0 and p.in_hand and not p.folded})
        pots, prev = [], 0
        for lvl in levels:
            amount = sum(min(p.total_bet, lvl) - min(p.total_bet, prev) for p in self.players)
            elig = [p for p in self.players if p.in_hand and not p.folded and p.total_bet >= lvl]
            pots.append({'amount': amount, 'eligible': elig})
            prev = lvl
        # chips from folded players above the top level
        extra = sum(max(0, p.total_bet - prev) for p in self.players)
        if extra and pots:
            pots[-1]['amount'] += extra
        return pots

    def _order_from_dealer(self, players):
        n = len(self.players)
        return sorted(players, key=lambda p: (self.players.index(p) - self.dealer - 1) % n)

    def _split_amount(self, amount, winners, why, awards):
        winners = self._order_from_dealer(winners)
        share, rem = divmod(amount, len(winners))
        for i, w in enumerate(winners):
            got = share + (1 if i < rem else 0)
            w.chips += got
            awards.append({'id': w.id, 'name': w.name, 'amount': got, 'why': why})

    def _showdown(self):
        live = self.contenders()
        shown = {p.id: self._evaluate(p) for p in live if p.declared}
        auto = {}

        def ev_of(p):
            if p.id in shown:
                return shown[p.id]
            if p.id not in auto:
                auto[p.id] = self._evaluate(p, auto=True)
            return auto[p.id]

        split = VARIANTS[self.variant]['split']
        side_name = SIDE_GAME_NAME.get(self.variant)
        result_pots = []
        for pot in self._build_pots():
            elig, awards = pot['eligible'], []
            if len(elig) == 1:
                self._split_amount(pot['amount'], elig, 'Uncalled / only player left', awards)
            else:
                # a player who didn't confirm mucks; if nobody in this pot confirmed, best hands are used
                contest = [p for p in elig if p.declared] or elig
                top = max(ev_of(p)['main'][0] for p in contest)
                main_w = [p for p in contest if ev_of(p)['main'][0] == top]
                if split:
                    stop = max(ev_of(p)['side'][0] for p in contest)
                    side_w = [p for p in contest if ev_of(p)['side'][0] == stop]
                    side_half = pot['amount'] // 2
                    self._split_amount(pot['amount'] - side_half, main_w,
                                       f'Texas: {ev_of(main_w[0])["main"][1]}', awards)
                    self._split_amount(side_half, side_w,
                                       f'{side_name}: {ev_of(side_w[0])["side"][1]}', awards)
                else:
                    self._split_amount(pot['amount'], main_w, ev_of(main_w[0])['main'][1], awards)
            result_pots.append({'amount': pot['amount'], 'awards': awards})
        for pot in result_pots:
            for a in pot['awards']:
                self.note(f'{a["name"]} wins {a["amount"]} — {a["why"]}')
        hands = {}
        for p in live:
            e = shown.get(p.id) or auto.get(p.id)
            if e is None:
                hands[p.id] = {'mucked': True}
                continue
            hands[p.id] = {'mucked': not p.declared, 'main': e['main'][1], 'use': e['use'],
                           'board': e['board'], 'side': e['side'][1] if 'side' in e else None,
                           'sideIdx': e.get('sideIdx')}
        self._finish({'uncontested': False, 'pots': result_pots, 'hands': hands, 'sideName': side_name})

    def auto_act(self):
        """Time ran out (or the player whose turn it is disconnected)."""
        if self.phase == 'choosing':
            self.choose_variant(self.players[self.sb], 'texas')
        elif self.phase in STREETS and self.to_act >= 0:
            p = self.players[self.to_act]
            self.act(p, 'check' if self.legal(p)['canCheck'] else 'fold')
        elif self.phase == 'declare':
            self.finish_declare()

    # ----- what each client sees -----

    def view(self, viewer_id):
        now = time.time()
        showdown = self.phase == 'handover' and self.result and not self.result['uncontested']
        me = self.find(viewer_id)
        idx = lambda i: self.players[i].id if 0 <= i < len(self.players) else None
        dealer_id, sb_id, bb_id = idx(self.dealer), idx(self.sb), idx(self.bb)
        turn_id = idx(self.to_act) if self.phase in STREETS + ['choosing'] else None
        playing = self.phase in ACTIVE
        roster = set(id(p) for p in self.players)
        seats = []
        for p in self.members:
            in_roster = id(p) in roster
            mucked = showdown and self.result['hands'].get(p.id, {}).get('mucked')
            reveal = p.id == viewer_id or (in_roster and p.hole and (
                (showdown and p.in_hand and not p.folded and not mucked) or
                (self.phase == 'handover' and p.shown)))
            live_cards = in_roster and p.in_hand and not p.folded
            seats.append({
                'id': p.id, 'name': p.name, 'seat': p.seat, 'seatRequest': p.seat_request,
                'chips': p.chips, 'bet': p.bet if in_roster else 0, 'connected': p.connected,
                'sittingOut': p.sitting_out, 'declared': p.declared, 'kicked': p.kicked,
                'inHand': in_roster and p.in_hand, 'folded': p.folded, 'allIn': p.all_in,
                'lastAction': p.last_action if in_roster else '',
                'cards': (p.hole if reveal else (['??'] * len(p.hole) if live_cards else [])) if in_roster else [],
                'shown': p.shown,
                'net': p.chips + p.buyout - p.buyin_total + (p.total_bet if playing and in_roster else 0),
                'buyinTotal': p.buyin_total, 'buyout': p.buyout, 'pendingCashout': p.pending_cashout,
                'history': p.history, 'buyins': p.buyins, 'handsWon': p.hands_won,
                'dealer': p.id == dealer_id and self.started, 'sb': p.id == sb_id and self.started,
                'bb': p.id == bb_id and self.started, 'turn': p.id == turn_id,
                'sideIdx': p.side_idx if p.id == viewer_id else None,
                'useIdx': p.use_idx if p.id == viewer_id else None,
                'emote': {'e': p.emote, 't': p.emote_t} if p.emote and now - p.emote_t < 6 else None,
            })
        mine = me if me in self.players else None
        return {
            'code': self.code, 'you': viewer_id, 'hostId': self.host_id, 'started': self.started,
            'phase': self.phase, 'variant': self.variant, 'paused': self.paused,
            'variantName': VARIANTS[self.variant]['name'] if self.variant else None,
            'split': bool(self.variant and VARIANTS[self.variant]['split']),
            'board': self.board, 'pot': self.pot_total() if playing else 0, 'seats': seats,
            'chooser': self.players[self.sb].id if self.phase == 'choosing' else None,
            'legal': self.legal(mine) if mine else None, 'result': self.result, 'log': self.log[-200:],
            'handNo': self.hand_no, 'canStart': self.can_start_hand(),
            'preview': self.preview(mine) if mine else None,
            'allowed': list(self.allowed_counts()) if self.variant else [],
            'declareLeft': max(0, self.declare_deadline - (self.paused_at if self.paused else now)) if self.phase == 'declare' else 0,
            'turnLeft': max(0, self.turn_deadline - (self.paused_at if self.paused else now)) if self.turn_deadline and turn_id else 0,
            'settings': self.settings, 'nextSettings': self.next_settings,
            'maxSeats': MAX_SEATS, 'emotes': EMOTES,
            'blinds': [self.settings['sb'], self.settings['bb']], 'startingChips': self.settings['stack'],
        }
