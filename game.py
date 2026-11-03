"""Table state and rules: blinds, betting rounds, side pots and split-pot showdowns."""
import random
import secrets
import time

import evaluator as ev

STARTING_CHIPS = 200
SMALL_BLIND = 1
BIG_BLIND = 2
DECLARE_SECONDS = 30   # time to make the final 999 / Theenpathi pick at showdown

VARIANTS = {
    'texas': {'name': "Texas Hold'em", 'hole': 2, 'split': False},
    '999': {'name': '999', 'hole': 5, 'split': True},
    '135': {'name': '1 3 5', 'hole': 5, 'split': False},
    'theenpathi': {'name': 'Theenpathi', 'hole': 5, 'split': True},
    'omaha': {'name': 'Omaha', 'hole': 4, 'split': False},
}
SIDE_GAME_NAME = {'999': '999', 'theenpathi': 'Theenpathi'}
STREETS = ['preflop', 'flop', 'turn', 'river']


def new_deck():
    deck = [r + s for r in ev.RANKS for s in 'shdc']
    random.SystemRandom().shuffle(deck)
    return deck


class Player:
    def __init__(self, name):
        self.id = secrets.token_hex(4)
        self.token = secrets.token_urlsafe(16)  # secret used to reconnect to this seat
        self.name = name
        self.chips = STARTING_CHIPS
        self.buyins = 1
        self.connected = True
        self.sitting_out = False
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
        self.last_action = ''

    @property
    def active(self):
        """Still able to make betting decisions."""
        return self.in_hand and not self.folded and not self.all_in


class Game:
    def __init__(self, code):
        self.code = code
        self.players = []        # seat order
        self.host_id = None
        self.started = False
        self.phase = 'lobby'     # lobby | choosing | preflop | flop | turn | river | declare | handover
        self.dealer = -1
        self.sb = self.bb = -1
        self.to_act = -1
        self.variant = None
        self.board = []
        self.deck = []
        self.current_bet = 0
        self.min_raise = BIG_BLIND
        self.hand_no = 0
        self.result = None       # summary of the last finished hand
        self.declare_deadline = 0
        self.log = []

    # ----- seating -----

    def add_player(self, name):
        p = Player(name)
        self.players.append(p)
        if self.host_id is None:
            self.host_id = p.id
        self.note(f'{name} joined the table')
        return p

    def find(self, pid):
        return next((p for p in self.players if p.id == pid), None)

    def ensure_host(self):
        host = self.find(self.host_id)
        if host is None or not host.connected:
            nxt = next((p for p in self.players if p.connected), None)
            if nxt:
                self.host_id = nxt.id

    def note(self, msg):
        self.log.append(msg)
        self.log = self.log[-60:]

    def rebuy(self, p):
        if p.in_hand and not p.folded and self.phase in STREETS + ['choosing', 'declare']:
            raise ValueError('You can only rebuy when you are not in a hand')
        if p.chips > 0:
            raise ValueError('You can only rebuy when you are out of chips')
        p.chips += STARTING_CHIPS
        p.buyins += 1
        self.note(f'{p.name} rebought for {STARTING_CHIPS}')

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

    # ----- hand flow -----

    def can_start_hand(self):
        return sum(1 for p in self.players if p.chips > 0 and p.connected and not p.sitting_out) >= 2

    def start_hand(self):
        if not self.can_start_hand():
            self.phase = 'lobby' if not self.started else 'handover'
            return False
        self.started = True
        self.hand_no += 1
        self.result = None
        self.board = []
        self.variant = None
        for p in self.players:
            p.reset_hand()
            p.in_hand = p.chips > 0 and p.connected and not p.sitting_out
        eligible = lambda p: p.in_hand
        self.dealer = self.next_seat(self.dealer, eligible)
        if len(self.in_hand_players()) == 2:  # heads-up: dealer posts the small blind
            self.sb = self.dealer
        else:
            self.sb = self.next_seat(self.dealer, eligible)
        self.bb = self.next_seat(self.sb, eligible)
        self.phase = 'choosing'
        self.to_act = self.sb
        self.note(f'--- Hand #{self.hand_no}: {self.players[self.sb].name} (small blind) is choosing the game ---')
        return True

    def choose_variant(self, p, variant):
        if self.phase != 'choosing' or self.players[self.sb] is not p:
            raise ValueError('Only the small blind can choose the game right now')
        if variant not in VARIANTS:
            raise ValueError('Unknown variant')
        self.variant = variant
        self.note(f'{p.name} chose {VARIANTS[variant]["name"]}')
        self.deck = new_deck()
        n_hole = VARIANTS[variant]['hole']
        for pl in self.in_hand_players():
            pl.hole = [self.deck.pop() for _ in range(n_hole)]
        self._post(self.players[self.sb], SMALL_BLIND, 'SB')
        self._post(self.players[self.bb], BIG_BLIND, 'BB')
        self.current_bet = BIG_BLIND
        self.min_raise = BIG_BLIND
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
        if self.phase not in STREETS or self.to_act < 0 or self.players[self.to_act] is not p:
            return None
        to_call = min(self.current_bet - p.bet, p.chips)
        max_to = p.bet + p.chips  # raise "to" amount when going all-in
        min_to = min(self.current_bet + self.min_raise if self.current_bet else BIG_BLIND, max_to)
        can_raise = max_to > self.current_bet and any(
            q.active and q is not p for q in self.players)
        return {'toCall': to_call, 'canCheck': to_call == 0, 'canRaise': can_raise,
                'minTo': min_to, 'maxTo': max_to, 'currentBet': self.current_bet}

    def act(self, p, action, amount=0):
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
        self.min_raise = BIG_BLIND
        n = 3 if not self.board else 1
        self.deck.pop()  # burn
        self.board += [self.deck.pop() for _ in range(n)]
        self.phase = STREETS[min(STREETS.index(self.phase) + 1, 3)] if self.phase in STREETS else 'flop'
        self.note(f'{self.phase.capitalize()}: {" ".join(self.board)}')

    # ----- endings -----

    def _finish(self, result):
        self.result = result
        self.phase = 'handover'
        self.to_act = -1
        for q in self.players:
            q.bet = 0

    def _win_uncontested(self, w):
        pot = self.pot_total()
        w.chips += pot
        self.note(f'{w.name} wins {pot} (everyone else folded)')
        self._finish({'uncontested': True, 'pots': [{'amount': pot, 'awards': [
            {'id': w.id, 'name': w.name, 'amount': pot, 'why': 'Everyone else folded'}]}],
            'hands': {}})

    def _reach_showdown(self):
        """Split games pause here so everyone makes their final pick with the full board out."""
        if VARIANTS[self.variant]['split']:
            self.phase = 'declare'
            self.to_act = -1
            self.declare_deadline = time.time() + DECLARE_SECONDS
            for q in self.players:
                q.bet = 0
            self.note(f'Showdown: pick your final {SIDE_GAME_NAME[self.variant]} cards')
        else:
            self._showdown()

    def set_split(self, p, idx):
        if not VARIANTS.get(self.variant, {}).get('split') or not p.in_hand or p.folded:
            raise ValueError('This game has no card split')
        if self.phase not in STREETS + ['declare'] or p.declared:
            raise ValueError('Your pick is final')
        idx = sorted(set(int(i) for i in idx))
        if len(idx) != 3 or any(i < 0 or i >= len(p.hole) for i in idx):
            raise ValueError('Pick exactly 3 cards')
        p.side_idx = idx

    def declare(self, p, idx):
        if self.phase != 'declare':
            raise ValueError('You confirm your pick at showdown')
        self.set_split(p, idx)
        p.declared = True
        self.note(f'{p.name} confirmed their {SIDE_GAME_NAME[self.variant]} cards')
        if all(q.declared for q in self.contenders()):
            self._showdown()

    def finish_declare(self):
        """Time's up: anyone who hasn't confirmed keeps their current pick (or the best 3 cards)."""
        if self.phase == 'declare':
            self._showdown()

    def _evaluate(self, p):
        v = self.variant
        if v == 'texas':
            s, d, _ = ev.best_holdem(p.hole, self.board)
            return {'main': (s, d)}
        if v == 'omaha':
            s, d, _ = ev.best_omaha(p.hole, self.board)
            return {'main': (s, d)}
        if v == '135':
            s, d, _ = ev.best_135(p.hole, self.board)
            return {'main': (s, d)}
        # split games: 3 cards go to the side game, the other 2 play Texas with the board
        if p.side_idx is None:
            p.side_idx = list(ev.best_999_split(p.hole) if v == '999' else ev.best_tp_split(p.hole))
        side_cards = [p.hole[i] for i in p.side_idx]
        texas_cards = [c for i, c in enumerate(p.hole) if i not in p.side_idx]
        ts, td, _ = ev.best_holdem(texas_cards, self.board)
        side = ev.eval_999(side_cards) if v == '999' else ev.eval_tp(side_cards)
        return {'main': (ts, td), 'side': side}

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
        evals = {p.id: self._evaluate(p) for p in live}
        split = VARIANTS[self.variant]['split']
        side_name = SIDE_GAME_NAME.get(self.variant)
        result_pots = []
        for pot in self._build_pots():
            elig, awards = pot['eligible'], []
            if len(elig) == 1:
                self._split_amount(pot['amount'], elig, 'Uncalled / only player left', awards)
            else:
                top = max(evals[p.id]['main'][0] for p in elig)
                main_w = [p for p in elig if evals[p.id]['main'][0] == top]
                main_label = 'Texas' if split else 'Best hand'
                if split:
                    stop = max(evals[p.id]['side'][0] for p in elig)
                    side_w = [p for p in elig if evals[p.id]['side'][0] == stop]
                    side_half = pot['amount'] // 2
                    main_half = pot['amount'] - side_half
                    self._split_amount(main_half, main_w,
                                       f'{main_label}: {evals[main_w[0].id]["main"][1]}', awards)
                    self._split_amount(side_half, side_w,
                                       f'{side_name}: {evals[side_w[0].id]["side"][1]}', awards)
                else:
                    self._split_amount(pot['amount'], main_w, evals[main_w[0].id]['main'][1], awards)
            result_pots.append({'amount': pot['amount'], 'awards': awards})
        for pot in result_pots:
            for a in pot['awards']:
                self.note(f'{a["name"]} wins {a["amount"]} — {a["why"]}')
        hands = {}
        for p in live:
            e = evals[p.id]
            hands[p.id] = {'main': e['main'][1], 'side': e['side'][1] if 'side' in e else None,
                           'sideIdx': p.side_idx}
        self._finish({'uncontested': False, 'pots': result_pots, 'hands': hands, 'sideName': side_name})

    def auto_act(self):
        """Used when the player whose turn it is has disconnected."""
        if self.phase == 'choosing':
            self.choose_variant(self.players[self.sb], 'texas')
        elif self.phase in STREETS and self.to_act >= 0:
            p = self.players[self.to_act]
            self.act(p, 'check' if self.legal(p)['canCheck'] else 'fold')
        elif self.phase == 'declare':
            self.finish_declare()

    # ----- what each client sees -----

    def view(self, viewer_id):
        showdown = self.phase == 'handover' and self.result and not self.result['uncontested']
        me = self.find(viewer_id)
        seats = []
        for i, p in enumerate(self.players):
            reveal = p.id == viewer_id or (showdown and p.in_hand and not p.folded)
            seats.append({
                'id': p.id, 'name': p.name, 'chips': p.chips, 'bet': p.bet, 'connected': p.connected,
                'sittingOut': p.sitting_out, 'declared': p.declared,
                'inHand': p.in_hand, 'folded': p.folded, 'allIn': p.all_in, 'lastAction': p.last_action,
                'cards': p.hole if reveal else (['??'] * len(p.hole) if p.in_hand and not p.folded else []),
                'net': p.chips - p.buyins * STARTING_CHIPS + (p.total_bet if self.phase in STREETS + ['declare'] else 0),
                'buyins': p.buyins, 'dealer': i == self.dealer, 'sb': i == self.sb and self.started,
                'bb': i == self.bb and self.started, 'turn': i == self.to_act and self.phase in STREETS + ['choosing'],
                'sideIdx': p.side_idx if reveal else None,
            })
        return {
            'code': self.code, 'you': viewer_id, 'hostId': self.host_id, 'started': self.started,
            'phase': self.phase, 'variant': self.variant,
            'variantName': VARIANTS[self.variant]['name'] if self.variant else None,
            'split': bool(self.variant and VARIANTS[self.variant]['split']),
            'board': self.board, 'pot': self.pot_total() if self.phase in STREETS + ['declare'] else 0, 'seats': seats,
            'chooser': self.players[self.sb].id if self.phase == 'choosing' else None,
            'legal': self.legal(me) if me else None, 'result': self.result, 'log': self.log[-25:],
            'handNo': self.hand_no, 'canStart': self.can_start_hand(),
            'declareLeft': max(0, round(self.declare_deadline - time.time())) if self.phase == 'declare' else 0,
            'blinds': [SMALL_BLIND, BIG_BLIND], 'startingChips': STARTING_CHIPS,
        }
