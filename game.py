"""Table state and rules: blinds, betting rounds, side pots and split-pot showdowns."""
import random
import secrets
import time

from itertools import combinations

import evaluator as ev

STARTING_CHIPS = 200
SMALL_BLIND = 1
BIG_BLIND = 2
DECLARE_SECONDS = 60   # time to choose your cards at showdown (no choice = muck)

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
        self.pending_buyins = 0  # bought during a hand: chips arrive when the hand ends
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
        self.use_idx = None   # hole cards chosen for the poker hand at showdown
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
        """Buy in for another stack at any time; mid-hand it is added once the hand ends."""
        if p.in_hand and not p.folded and self.phase in STREETS + ['choosing', 'declare']:
            p.pending_buyins += 1
            self.note(f'{p.name} bought in for {STARTING_CHIPS} (added after this hand)')
        else:
            self._add_buyin(p)
            self.note(f'{p.name} bought in for {STARTING_CHIPS} (buy-in #{p.buyins})')

    def _add_buyin(self, p):
        p.chips += STARTING_CHIPS
        p.buyins += 1

    def _apply_pending_buyins(self):
        for p in self.players:
            while p.pending_buyins:
                p.pending_buyins -= 1
                self._add_buyin(p)
                self.note(f'{p.name}: buy-in #{p.buyins} added')

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
        self._apply_pending_buyins()
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

    # ----- showdown: each player picks which of their own cards they use -----

    def allowed_counts(self):
        """How many hole cards may go into the poker hand (for split games: of the 2 non-side cards)."""
        return {'texas': (0, 1, 2), 'omaha': (2,), '135': (1, 3, 5),
                '999': (0, 1, 2), 'theenpathi': (0, 1, 2)}[self.variant]

    def _reach_showdown(self):
        """Pause with the full board out so everyone picks the cards they play."""
        self.phase = 'declare'
        self.to_act = -1
        self.declare_deadline = time.time() + DECLARE_SECONDS
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
            mucked = showdown and self.result['hands'].get(p.id, {}).get('mucked')
            reveal = p.id == viewer_id or (showdown and p.in_hand and not p.folded and not mucked)
            seats.append({
                'id': p.id, 'name': p.name, 'chips': p.chips, 'bet': p.bet, 'connected': p.connected,
                'sittingOut': p.sitting_out, 'declared': p.declared,
                'inHand': p.in_hand, 'folded': p.folded, 'allIn': p.all_in, 'lastAction': p.last_action,
                'cards': p.hole if reveal else (['??'] * len(p.hole) if p.in_hand and not p.folded else []),
                'net': p.chips - p.buyins * STARTING_CHIPS + (p.total_bet if self.phase in STREETS + ['declare'] else 0),
                'buyins': p.buyins, 'pendingBuyins': p.pending_buyins, 'dealer': i == self.dealer, 'sb': i == self.sb and self.started,
                'bb': i == self.bb and self.started, 'turn': i == self.to_act and self.phase in STREETS + ['choosing'],
                'sideIdx': p.side_idx if p.id == viewer_id else None,
                'useIdx': p.use_idx if p.id == viewer_id else None,
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
            'preview': self.preview(me) if me else None,
            'allowed': list(self.allowed_counts()) if self.variant else [],
            'declareLeft': max(0, round(self.declare_deadline - time.time())) if self.phase == 'declare' else 0,
            'blinds': [SMALL_BLIND, BIG_BLIND], 'startingChips': STARTING_CHIPS,
        }
