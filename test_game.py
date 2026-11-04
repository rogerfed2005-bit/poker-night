"""Run: py test_game.py"""
import random

import evaluator as ev
import time

from game import Game, VARIANTS, STREETS, STARTING_CHIPS, ACTIVE


def check_evaluators():
    s = lambda cards: ev.eval5(cards.split())[0]
    assert s('As Ks Qs Js Ts') > s('9h 9d 9c 9s 2h')        # royal > quads
    assert s('Ah 2d 3c 4s 5h') < s('2d 3c 4s 5h 6h')        # wheel is the lowest straight
    assert s('Kh Kd 2c 2s 9h') > s('Qh Qd Jc Js Ah')        # two pair by top pair
    assert ev.eval_999('9s 8d 7c'.split())[0] == 987
    assert ev.eval_999('Ts 9d Ac'.split())[0] == 900       # 10/J/Q/K/A are zeros
    t = lambda cards: ev.eval_tp(cards.split())[0]
    assert t('2s 2d 2c') > t('As Ks Qs')                    # trail > straight flush
    assert t('4s 5s 6s') > t('As Kd Qc')                    # straight flush > straight
    assert t('4h 5d 6c') > t('Ah Kh 9h')                    # straight > flush
    assert t('Ah Kh 9h') > t('Ad Ac Kc')                    # flush > pair
    assert t('As Kd Qc') > t('Ah 2d 3c')                    # AKQ top straight, A23 bottom
    # Omaha must use exactly two hole cards: four hearts in hand + 1 on board is no flush
    sc, desc, _ = ev.best_omaha('Ah Kh Qh Jh'.split(), '2h 7c 8d 9s 3c'.split())
    assert 'Flush' not in desc, desc
    # 1-3-5: with hole 5 hearts the player may use all five
    sc, desc, _ = ev.best_135('2h 5h 7h 9h Jh'.split(), 'Ac Ad As Kc Kd'.split())
    assert desc.startswith('Flush') or 'Full House' in desc
    # ...but can't use exactly 2 hole cards: hole pair + board trips would need 2 hole + 3 board
    sc, desc, _ = ev.best_135('Qh Qd 2c 3c 4d'.split(), 'Qs 9c 9d 7h 8s'.split())
    assert desc == 'Three Queens', desc          # QQ+Q99 full house would need 2 hole + 3 board
    print('evaluators ok')


def declare_random(g, p):
    """Confirm a random legal choice of hole cards (and side cards in split games)."""
    side = random.sample(range(5), 3) if VARIANTS[g.variant]['split'] else None
    avail = [i for i in range(len(p.hole)) if not side or i not in side]
    use = random.sample(avail, random.choice(g.allowed_counts()))
    g.declare(p, use, side)


def finish_by_declaring(g, picks=None):
    """Play out a showdown; picks maps player -> (use, side), everyone else picks randomly."""
    picks = picks or {}
    for p in g.contenders():
        if g.phase != 'declare':
            break
        if p in picks:
            g.declare(p, *picks[p])
        else:
            declare_random(g, p)


def play_random_hands(n_hands=3000, seed=1):
    random.seed(seed)
    g = Game('TEST')
    players = [g.add_player(f'P{i}') for i in range(random.randint(2, 8))]
    total = STARTING_CHIPS * len(players)
    variants = list(VARIANTS)
    for hand in range(n_hands):
        for p in players:
            if p.kicked:
                continue
            if p.seat is None:
                g.request_seat(p, g.free_seats()[0])
                if p.seat_request is not None:
                    g.answer_request(g.find(g.host_id), p, True)
                total += STARTING_CHIPS
            elif p.chips == 0:
                g.rebuy(p)
                total += STARTING_CHIPS
        if hand % 50 == 25:                     # the host changes blinds and antes between hands
            g.update_settings(g.find(g.host_id), {'sb': random.choice([1, 2, 5]), 'bb': 10, 'ante': random.choice([0, 1, 3])})
        assert g.start_hand()
        g.choose_variant(g.players[g.sb], random.choice(variants))
        if VARIANTS[g.variant]['split']:
            for p in g.in_hand_players():
                if random.random() < 0.5:
                    g.set_split(p, random.sample(range(5), 3))
        steps = 0
        while g.phase in STREETS:
            p = g.players[g.to_act]
            lg = g.legal(p)
            if lg is None:                      # hand ended by a removal inside this loop
                break
            if random.random() < 0.01:          # buying in mid-hand is refused for anyone dealt in
                q = random.choice([q for q in players if not q.kicked and q.seat is not None])
                try:
                    g.rebuy(q)
                    assert not q.in_hand, 'bought in mid-hand'
                    total += STARTING_CHIPS
                except ValueError:
                    assert q.in_hand or q.pending_cashout
            seated = [q for q in players if not q.kicked]
            if random.random() < 0.003 and len(seated) > 3 and g.phase in STREETS:
                g.kick(g.find(g.host_id), random.choice([q for q in seated if q.id != g.host_id]))
                continue                        # whose turn it is may have changed
            if random.random() < 0.005:         # cash-outs too
                q = random.choice([q for q in players if not q.kicked])
                if q.seat is not None and not q.pending_cashout:
                    g.cash_out(q)
            r = random.random()
            if r < 0.15 and not lg['canCheck']:
                g.act(p, 'fold')
            elif r < 0.3 and lg['canRaise']:
                g.act(p, 'raise', random.randint(lg['minTo'], lg['maxTo']))
            else:
                g.act(p, 'check' if lg['canCheck'] else 'call')
            steps += 1
            assert steps < 500, 'hand never ended'
        if g.phase == 'declare':
            assert len(g.board) == 5
            live = g.contenders()
            for p in live:
                r = random.random()
                if r < 0.15:
                    continue                    # never confirms: mucks when the timer runs out
                if r < 0.25:                    # an illegal pick is refused
                    try:
                        g.declare(p, list(range(len(p.hole))), [0, 1, 2] if VARIANTS[g.variant]['split'] else None)
                        if g.variant not in ('135', 'texas'):
                            raise AssertionError('illegal pick accepted')
                    except ValueError:
                        pass
                if not p.declared and g.phase == 'declare':
                    declare_random(g, p)
            g.finish_declare()
        assert g.phase == 'handover'
        assert all(not p.pending_cashout for p in players)
        assert sum(p.chips + p.buyout for p in players) == total, 'chips not conserved'
        assert all(sum(h['amount'] for h in p.history if h['kind'] == 'Buy-in') == p.buyins * STARTING_CHIPS for p in players)
        assert all(sum(h['amount'] for h in p.history if h['kind'] == 'Buy-out') == p.buyout for p in players)
        assert sum(p.buyins for p in players) * STARTING_CHIPS == total, 'buy-ins miscounted'
        if not g.result['uncontested']:
            assert len(g.board) == 5
    print(f'{n_hands} random hands ok ({len(players)} players)')


def check_999_split():
    g = Game('T999')
    a, b, c, d = (g.add_player(n) for n in 'ABCD')
    g.start_hand()
    g.choose_variant(g.players[g.sb], '999')
    a.hole, b.hole = 'As Ad 2c 3d 4h'.split(), '9s 9d 8c 2s 3s'.split()
    c.hole, d.hole = '9c 9h 8d 2h 3h'.split(), '4c 4d 5h 5d 7d'.split()
    g.set_split(a, [2, 3, 4]); g.set_split(b, [0, 1, 2]); g.set_split(c, [0, 1, 2]); g.set_split(d, [2, 3, 4])
    g.deck = 'Jh 6d 5c 6h 7s Qd Kc 6s'.split()   # popped from the end: burn, Kc Qd 7s, burn, 5c, burn, Jh
    while g.phase in STREETS:
        p = g.players[g.to_act]
        g.act(p, 'check' if g.legal(p)['canCheck'] else 'call')
    assert g.phase == 'declare'
    g.set_split(a, [0, 1, 2])          # change of mind at showdown...
    g.declare(a, [0, 1], [2, 3, 4])    # ...final pick is what counts: AA for Texas
    try:
        g.set_split(a, [0, 1, 2])
        raise AssertionError('pick changed after confirming')
    except ValueError:
        pass
    g.declare(b, [3, 4], [0, 1, 2]); g.declare(c, [3, 4], [0, 1, 2])
    assert g.phase == 'declare'        # still waiting for D
    g.declare(d, [0, 1], [2, 3, 4])
    assert g.result['hands'][a.id]['main'] == 'Pair of Aces'
    assert g.result['hands'][a.id]['use'] == [0, 1]
    won = {}
    for pot in g.result['pots']:
        for aw in pot['awards']:
            won[aw['name']] = won.get(aw['name'], 0) + aw['amount']
    # pot 8: A takes the Texas half (4), B and C tie 998 and get a quarter each (2)
    assert won == {'A': 4, 'B': 2, 'C': 2}, won
    print('999 split + showdown pick ok')


def refused(fn, *args):
    try:
        fn(*args)
    except ValueError:
        return True
    return False


def check_buyin_between_hands():
    g = Game('TBUY')
    a, b, c = g.add_player('A'), g.add_player('B'), g.add_player('C')
    g.rebuy(a)                                   # before the game: added now
    assert (a.chips, a.buyins) == (2 * STARTING_CHIPS, 2)
    c.chips = 0                                  # busted: not dealt in, so free to buy in mid-hand
    g.start_hand()
    assert not c.in_hand
    g.choose_variant(g.players[g.sb], 'texas')
    assert refused(g.rebuy, b)                   # dealt in: not in the middle of a hand
    p = g.players[g.to_act]
    g.act(p, 'fold')
    if g.phase in ACTIVE:
        assert refused(g.rebuy, p)               # folded is still this hand
    g.rebuy(c)
    assert c.chips == STARTING_CHIPS
    while g.phase in STREETS:
        q = g.players[g.to_act]
        g.act(q, 'check' if g.legal(q)['canCheck'] else 'call')
    finish_by_declaring(g)
    g.rebuy(b)                                   # hand over: allowed
    assert b.buyins == 2
    w = Game('TW')                               # a watcher must sit first
    w.add_player('H')
    x = w.add_member('X')
    assert refused(w.rebuy, x)
    print('buy-in only between hands ok')


def check_seats_and_settings():
    g = Game('TS')
    h = g.add_member('Host')
    g.request_seat(h, 4)                         # the host sits straight away
    assert h.seat == 4 and h.chips == STARTING_CHIPS
    x, y = g.add_member('X'), g.add_member('Y')
    g.request_seat(x, 2)                         # others wait for approval
    assert x.seat is None and x.seat_request == 2
    assert refused(g.request_seat, y, 2)         # seat already requested
    assert refused(g.answer_request, x, x, True) # only the host approves
    g.answer_request(h, x, True)
    assert x.seat == 2 and x.chips == STARTING_CHIPS and x.buyins == 1
    g.request_seat(y, 6)
    g.answer_request(h, y, False)
    assert y.seat is None and y.seat_request is None and y.buyins == 0
    g.update_settings(h, {'approval': False})
    g.request_seat(y, 6)
    assert y.seat == 6
    # blinds and stack: right away between hands, from the next hand mid-hand
    g.update_settings(h, {'sb': 5, 'bb': 10, 'stack': 1000})
    assert g.start_hand()
    assert [p.seat for p in g.players] == [2, 4, 6] and g.dealer_seat == 2
    g.choose_variant(g.players[g.sb], 'texas')
    assert g.current_bet == 10
    g.update_settings(h, {'bb': 20, 'ante': 2})
    assert g.settings['bb'] == 10 and g.next_settings['bb'] == 20
    assert refused(g.update_settings, h, {'sb': 50})        # bigger than the big blind
    assert refused(g.update_settings, x, {'sb': 1})         # not the host
    while g.phase in STREETS:
        q = g.players[g.to_act]
        g.act(q, 'check' if g.legal(q)['canCheck'] else 'call')
    finish_by_declaring(g)
    z = g.add_member('Z')                        # a new player sits between hands
    g.request_seat(z, 3)
    assert g.start_hand() and g.settings['bb'] == 20 and g.dealer_seat == 3
    g.choose_variant(g.players[g.sb], 'texas')
    assert g.pot_total() == 4 * 2 + 5 + 20        # antes + blinds
    assert z.buyin_total == 1000
    # pause: no actions, the clock stops
    g.set_paused(h, True)
    q = g.players[g.to_act]
    assert g.legal(q) is None and refused(g.act, q, 'fold')
    left = g.turn_deadline
    time.sleep(0.05)
    g.set_paused(h, False)
    assert g.turn_deadline > left and g.legal(q)
    # leaving mid-hand frees the seat after the hand; the seat can be taken again later
    g.cash_out(q)
    assert q.pending_cashout and q.seat is not None
    while g.phase in STREETS:
        r = g.players[g.to_act]
        g.act(r, 'check' if g.legal(r)['canCheck'] else 'call')
    finish_by_declaring(g)
    assert q.seat is None and q.chips == 0 and q.buyout > 0
    total_in = sum(p.buyin_total for p in g.members)
    assert sum(p.chips + p.buyout for p in g.members) == total_in
    # show cards after the hand
    r = next(p for p in g.players if p.hole)
    g.show_cards(r)
    assert g.view(h.id)['seats'][g.members.index(r)]['cards'] == r.hole
    # hand over hosting
    g.make_host(h, x)
    assert g.host_id == x.id and refused(g.set_paused, h, True)
    print('seats, approval, settings, pause ok')


def heads_up(variant, hole_a, hole_b, board):
    g = Game('T')
    a, b = g.add_player('A'), g.add_player('B')
    g.start_hand()
    g.choose_variant(g.players[g.sb], variant)
    a.hole, b.hole = hole_a.split(), hole_b.split()
    burns = ['2c', '2d', '2h']
    bd = board.split()
    g.deck = [bd[4], burns[0], bd[3], burns[1], bd[2], bd[1], bd[0], burns[2]]
    while g.phase in STREETS:
        p = g.players[g.to_act]
        g.act(p, 'check' if g.legal(p)['canCheck'] else 'call')
    assert g.phase == 'declare'
    return g, a, b


def check_players_choose_their_cards():
    # Texas: A holds a flush draw that got there; B has top pair
    g, a, b = heads_up('texas', 'Ah 9h', 'Ks Qd', 'Kh 7h 3h 8c 4s')
    g.set_use(a, [0, 1])
    assert g.preview(a)['desc'] == 'Flush, Ace high'
    g.set_use(a, [])                   # playing the board is allowed in Texas
    assert g.preview(a)['desc'] == 'King High'
    g.declare(a, [1])                  # A misplays: only the 9h -> no flush, and the pick counts
    g.declare(b, [0, 1])
    assert g.result['hands'][a.id]['main'] == 'King High'
    won = {aw['name']: aw['amount'] for pot in g.result['pots'] for aw in pot['awards']}
    assert won == {'B': 4}, won
    assert sorted(g.result['hands'][b.id]['board']) == sorted(['Kh', '8c', '7h']), g.result['hands'][b.id]
    # Omaha: exactly 2 hole cards
    g, a, b = heads_up('omaha', 'Ah Kh Qh Jh', '2s 5d 9c 9d', 'Th 3h 6h 8c 9s')
    for wrong in ([0], [0, 1, 2]):
        try:
            g.declare(a, wrong)
            raise AssertionError('omaha accepted %r' % wrong)
        except ValueError:
            pass
    g.declare(a, [0, 1])
    g.declare(b, [2, 3])
    assert g.result['hands'][a.id]['main'] == 'Flush, Ace high'
    # 1 3 5: 2 cards not allowed
    g, a, b = heads_up('135', 'Qh Qd 2c 3c 4d', '5s 6s 7d 8d 9h', 'Qs 9c 9d 7h 8s')
    try:
        g.declare(a, [0, 1])
        raise AssertionError('135 accepted 2 cards')
    except ValueError:
        pass
    g.declare(a, [0])
    g.declare(b, [0, 1, 2])
    print('players choose their own cards ok')


def check_no_confirm_mucks():
    g, a, b = heads_up('texas', 'As Ad', '7c 2d', 'Kh 9h 3s 8c 4d')
    g.declare(b, [0, 1])               # B confirms 7-high; A (pair of aces) never confirms
    g.finish_declare()
    won = {aw['name']: aw['amount'] for pot in g.result['pots'] for aw in pot['awards']}
    assert won == {'B': 4}, won
    assert g.result['hands'][a.id]['mucked']
    # nobody confirms: best hands are used
    g, a, b = heads_up('texas', 'As Ad', '7c 2d', 'Kh 9h 3s 8c 4d')
    g.finish_declare()
    won = {aw['name']: aw['amount'] for pot in g.result['pots'] for aw in pot['awards']}
    assert won == {'A': 4}, won
    print('no confirm = muck ok')


def check_cash_out():
    g = Game('TCASH')
    a, b, c = g.add_player('A'), g.add_player('B'), g.add_player('C')
    g.cash_out(c)                                # between hands: immediate
    assert (c.chips, c.buyout, c.seat) == (0, STARTING_CHIPS, None)
    g.start_hand()
    assert not c.in_hand                         # not dealt while cashed out
    g.choose_variant(g.players[g.sb], 'texas')
    g.cash_out(a)                                # mid-hand: when the hand ends
    assert a.pending_cashout and a.buyout == 0
    while g.phase in STREETS:
        p = g.players[g.to_act]
        g.act(p, 'check' if g.legal(p)['canCheck'] else 'call')
    finish_by_declaring(g)
    assert a.seat is None and a.chips == 0 and a.buyout > 0
    assert a.buyout + b.chips == 2 * STARTING_CHIPS
    assert refused(g.rebuy, c)                   # left the table: sit down again to buy in
    g.request_seat(c, 5)
    g.answer_request(a, c, True)
    assert c.seat == 5 and not c.sitting_out and c.chips == STARTING_CHIPS and c.buyins == 2
    assert [h['kind'] for h in c.history] == ['Buy-in', 'Buy-out', 'Buy-in']
    v = {x['name']: x for x in g.view(c.id)['seats']}
    assert v['C']['net'] == 0 and v['C']['buyout'] == STARTING_CHIPS and v['C']['buyinTotal'] == 2 * STARTING_CHIPS
    print('cash out ok')


def table(n, variant='texas'):
    g = Game('TK')
    ps = [g.add_player(c) for c in 'ABCDEFGH'[:n]]
    g.start_hand()
    if variant:
        g.choose_variant(g.players[g.sb], variant)
    return g, ps


def conserved(g):
    in_pot = sum(p.total_bet for p in g.players) if g.phase != 'handover' else 0
    return sum(p.chips + p.buyout for p in g.members) + in_pot == sum(p.buyin_total for p in g.members)


def check_kick():
    # only the host, never themself
    g, (a, b, c) = table(3)
    for who, target in ((b, c), (a, a)):
        try:
            g.kick(who, target)
            raise AssertionError('kick allowed')
        except ValueError:
            pass
    # removed on their turn: they fold, the turn moves on, their stack is cashed out
    p = g.players[g.to_act]
    target = p if p is not a else g.players[g.next_seat(g.to_act, lambda q: q.active)]
    g.kick(a, target)
    assert target.kicked and target.folded and target.chips == 0 and target.buyout > 0
    assert g.phase in STREETS and g.players[g.to_act] is not target
    try:
        g.rebuy(target)
        raise AssertionError('kicked player bought in')
    except ValueError:
        pass
    while g.phase in STREETS:
        q = g.players[g.to_act]
        g.act(q, 'check' if g.legal(q)['canCheck'] else 'call')
    finish_by_declaring(g)
    assert g.phase == 'handover' and conserved(g)
    assert g.start_hand() and not target.in_hand          # not dealt again

    # removing the only other player ends the hand
    g, (a, b) = table(2)
    g.kick(a, b)
    assert g.phase == 'handover' and g.result['uncontested'] and conserved(g)

    # small blind removed while choosing the game: Texas is played without them
    g, ps = table(3, variant=None)
    host = ps[0]
    sb = g.players[g.sb]
    if sb is host:
        g.host_id = ps[1].id
        host = ps[1]
    g.kick(host, sb)
    assert g.variant == 'texas' and sb.folded and g.phase in STREETS and conserved(g)

    # removed at showdown while everyone else has confirmed: showdown happens
    g, (a, b, c) = table(3)
    while g.phase in STREETS:
        q = g.players[g.to_act]
        g.act(q, 'check' if g.legal(q)['canCheck'] else 'call')
    g.declare(a, [0, 1]); g.declare(b, [0, 1])
    g.kick(a, c)
    assert g.phase == 'handover' and conserved(g)
    assert c.id not in g.result['hands'] or g.result['hands'][c.id].get('mucked', True)
    print('host can remove players ok')


def check_allin_gets_showdown_pick():
    g = Game('TALL')
    a, b = g.add_player('A'), g.add_player('B')
    g.start_hand()
    g.choose_variant(g.players[g.sb], 'theenpathi')
    p = g.players[g.to_act]
    g.act(p, 'raise', 10_000)          # all-in pre-flop
    q = g.players[g.to_act]
    g.act(q, 'call')
    assert g.phase == 'declare' and len(g.board) == 5, g.phase
    print('all-in still gets showdown pick ok')


if __name__ == '__main__':
    check_evaluators()
    check_999_split()
    check_allin_gets_showdown_pick()
    check_buyin_between_hands()
    check_seats_and_settings()
    check_players_choose_their_cards()
    check_no_confirm_mucks()
    check_cash_out()
    check_kick()
    for seed in range(1, 6):
        play_random_hands(seed=seed)
