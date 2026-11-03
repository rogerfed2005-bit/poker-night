"""Run: py test_game.py"""
import random

import evaluator as ev
from game import Game, VARIANTS, STREETS, STARTING_CHIPS


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
    for _ in range(n_hands):
        for p in players:
            if p.chips == 0:
                g.rebuy(p)
                total += STARTING_CHIPS
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
            if random.random() < 0.01:          # buy-ins at random moments, mid-hand too
                g.rebuy(random.choice(players))
                total += STARTING_CHIPS
            if random.random() < 0.005:         # cash-outs too
                q = random.choice(players)
                if not (q.cashed_out or q.pending_cashout):
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
        assert all(p.pending_buyins == 0 for p in players)
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


def check_buyin_any_time():
    g = Game('TBUY')
    a, b = g.add_player('A'), g.add_player('B')
    g.rebuy(a)                                   # in the lobby: added now
    assert (a.chips, a.buyins) == (2 * STARTING_CHIPS, 2)
    g.start_hand()
    g.choose_variant(g.players[g.sb], 'texas')
    before = b.chips
    g.rebuy(b)                                   # mid-hand: queued
    assert (b.chips, b.buyins, b.pending_buyins) == (before, 1, 1)
    while g.phase in STREETS:
        p = g.players[g.to_act]
        g.act(p, 'check' if g.legal(p)['canCheck'] else 'call')
    finish_by_declaring(g)
    assert (b.buyins, b.pending_buyins) == (2, 0)
    assert a.chips + b.chips == 4 * STARTING_CHIPS
    print('buy-in any time ok')


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
    assert (c.chips, c.buyout, c.cashed_out) == (0, STARTING_CHIPS, True)
    g.start_hand()
    assert not c.in_hand                         # not dealt while cashed out
    g.choose_variant(g.players[g.sb], 'texas')
    g.cash_out(a)                                # mid-hand: when the hand ends
    assert a.pending_cashout and a.buyout == 0
    while g.phase in STREETS:
        p = g.players[g.to_act]
        g.act(p, 'check' if g.legal(p)['canCheck'] else 'call')
    finish_by_declaring(g)
    assert a.cashed_out and a.chips == 0 and a.buyout > 0
    assert a.buyout + b.chips == 2 * STARTING_CHIPS
    g.rebuy(c)                                   # buying back in returns you to the table
    assert not c.cashed_out and not c.sitting_out and c.chips == STARTING_CHIPS and c.buyins == 2
    assert [h['kind'] for h in c.history] == ['Buy-in', 'Buy-out', 'Buy-in']
    v = {x['name']: x for x in g.view(c.id)['seats']}
    assert v['C']['net'] == 0 and v['C']['buyout'] == STARTING_CHIPS and v['C']['buyinTotal'] == 2 * STARTING_CHIPS
    print('cash out ok')


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
    check_buyin_any_time()
    check_players_choose_their_cards()
    check_no_confirm_mucks()
    check_cash_out()
    for seed in range(1, 6):
        play_random_hands(seed=seed)
