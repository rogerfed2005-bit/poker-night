"""Hand evaluation for every variant.

Cards are 2-char strings: rank in '23456789TJQKA', suit in 'shdc' (e.g. 'As', 'Td').
Every evaluator returns (score, description); a higher score wins.
"""
from itertools import combinations

RANKS = '23456789TJQKA'
RANK_NAMES = {2: 'Two', 3: 'Three', 4: 'Four', 5: 'Five', 6: 'Six', 7: 'Seven', 8: 'Eight',
              9: 'Nine', 10: 'Ten', 11: 'Jack', 12: 'Queen', 13: 'King', 14: 'Ace'}
PLURAL = {6: 'Sixes'}


def rank_of(card):
    return RANKS.index(card[0]) + 2


def _plural(r):
    return PLURAL.get(r, RANK_NAMES[r] + 's')


def _encode(cat, kickers):
    s = cat
    for i in range(5):
        s = s * 15 + (kickers[i] if i < len(kickers) else 0)
    return s


# ---------- 5-card poker ----------

POKER_NAMES = ['High Card', 'Pair', 'Two Pair', 'Three of a Kind', 'Straight', 'Flush',
               'Full House', 'Four of a Kind', 'Straight Flush']


def eval5(cards):
    rs = sorted((rank_of(c) for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    counts = {}
    for r in rs:
        counts[r] = counts.get(r, 0) + 1
    groups = sorted(((n, r) for r, n in counts.items()), reverse=True)
    straight_high = 0
    if len(counts) == 5:
        if rs[0] - rs[4] == 4:
            straight_high = rs[0]
        elif rs == [14, 5, 4, 3, 2]:
            straight_high = 5
    g = [r for _, r in groups]
    if straight_high and flush:
        cat, kick = 8, [straight_high]
        desc = 'Royal Flush' if straight_high == 14 else f'Straight Flush, {RANK_NAMES[straight_high]} high'
    elif groups[0][0] == 4:
        cat, kick, desc = 7, g, f'Four {_plural(g[0])}'
    elif groups[0][0] == 3 and groups[1][0] == 2:
        cat, kick, desc = 6, g, f'Full House, {_plural(g[0])} full of {_plural(g[1])}'
    elif flush:
        cat, kick, desc = 5, rs, f'Flush, {RANK_NAMES[rs[0]]} high'
    elif straight_high:
        cat, kick, desc = 4, [straight_high], f'Straight, {RANK_NAMES[straight_high]} high'
    elif groups[0][0] == 3:
        cat, kick, desc = 3, g, f'Three {_plural(g[0])}'
    elif groups[0][0] == 2 and groups[1][0] == 2:
        cat, kick, desc = 2, g, f'Two Pair, {_plural(g[0])} and {_plural(g[1])}'
    elif groups[0][0] == 2:
        cat, kick, desc = 1, g, f'Pair of {_plural(g[0])}'
    else:
        cat, kick, desc = 0, rs, f'{RANK_NAMES[rs[0]]} High'
    return _encode(cat, kick), desc


def _best(candidates):
    best = None
    for five in candidates:
        score, desc = eval5(five)
        if best is None or score > best[0]:
            best = (score, desc, list(five))
    return best


def best_holdem(hole, board):
    """Best 5 of hole + board, any number of hole cards (Texas, and the Texas half of 999/Theenpathi)."""
    return _best(combinations(list(hole) + list(board), 5))


def best_omaha(hole, board):
    """Exactly 2 hole cards + exactly 3 board cards."""
    return _best(h + b for h in combinations(hole, 2) for b in combinations(board, 3))


def best_135(hole, board):
    """Exactly 1, 3 or 5 hole cards, the rest from the board."""
    return _best(h + b for k in (1, 3, 5)
                 for h in combinations(hole, k) for b in combinations(board, 5 - k))


# ---------- 999 ----------

def digit_999(card):
    r = rank_of(card)
    return r if r <= 9 else 0  # 10, J, Q, K, A count as 0


def eval_999(cards):
    d = sorted((digit_999(c) for c in cards), reverse=True)
    n = d[0] * 100 + d[1] * 10 + d[2]
    return n, f'{n:03d}'


def best_999_split(cards):
    """Pick the 3 cards giving the highest 999 number (used when a player doesn't choose)."""
    return max(combinations(range(len(cards)), 3), key=lambda idx: eval_999([cards[i] for i in idx])[0])


# ---------- Theenpathi (3-card) ----------
# Order: Trail (three of a kind) > Straight Flush > Straight > Flush > Pair > High Card.
# A-K-Q is the top straight and A-2-3 the lowest.

TP_NAMES = ['High Card', 'Pair', 'Flush', 'Straight', 'Straight Flush', 'Trail']


def eval_tp(cards):
    rs = sorted((rank_of(c) for c in cards), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    straight_high = 0
    if len(set(rs)) == 3:
        if rs[0] - rs[2] == 2:
            straight_high = rs[0]
        elif rs == [14, 3, 2]:
            straight_high = 3
    if rs[0] == rs[2]:
        cat, kick, desc = 5, rs, f'Trail of {_plural(rs[0])}'
    elif straight_high and flush:
        cat, kick, desc = 4, [straight_high], f'Straight Flush, {RANK_NAMES[straight_high]} high'
    elif straight_high:
        cat, kick, desc = 3, [straight_high], f'Straight, {RANK_NAMES[straight_high]} high'
    elif flush:
        cat, kick, desc = 2, rs, f'Flush, {RANK_NAMES[rs[0]]} high'
    elif rs[0] == rs[1] or rs[1] == rs[2]:
        pair = rs[1]
        kicker = rs[2] if rs[0] == rs[1] else rs[0]
        cat, kick, desc = 1, [pair, kicker], f'Pair of {_plural(pair)}'
    else:
        cat, kick, desc = 0, rs, f'{RANK_NAMES[rs[0]]} High'
    return _encode(cat, kick), desc


def best_tp_split(cards):
    return max(combinations(range(len(cards)), 3), key=lambda idx: eval_tp([cards[i] for i in idx])[0])
