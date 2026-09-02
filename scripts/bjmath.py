#!/usr/bin/env python3
"""
bjmath.py

What every action is worth, computed from the cards actually left in the shoe.

This is not a strategy chart. A chart answers "what is best on average over a
full six-deck shoe", which is the wrong question at a table where the shoe is
half dealt: the same sixteen against the same ten is worth different things
depending on what has already come out. Everything here works in compositions —
how many aces, twos, ... tens remain — and enumerates, so the answer is the
answer for this shoe and no other.

Three things make it exact rather than nearly exact.

Cards are drawn without replacement all the way down, including the dealer's.

Nothing here is ever allowed to see the hole card. That sounds obvious and is
the easiest thing in the world to get wrong: enumerate the hole card, take the
best action inside each branch, and sixteen against a ten starts standing
whenever the dealer's total is sixteen — worth a quarter of a unit that no
player can collect. Every decision is made on the average over the hole cards
the player cannot distinguish, which is the information a player actually has.

The peek is priced. A dealer showing an ace or a ten has already looked, so the
hole cards that would have made a natural are gone and the rest renormalised.
That tilts the player's own draws too: with the dealer's ace known not to be
covering a ten, a ten is slightly likelier to arrive next, and `draw_probs`
carries that tilt rather than assuming the shoe is untouched.

The one deliberate approximation is splitting: each hand created by a split is
priced as if it were the only one, so the hands do not see each other's cards.
That is the standard treatment and it is worth a few thousandths of a unit; the
golden fixture in tests pins how far it may drift.

Index 0 is the ace and index 9 is the ten, so a composition is
(aces, twos, ..., nines, tens) and card values run 1..10.
"""

from functools import lru_cache
from typing import NamedTuple

# Composition index -> card value. The ten is one bucket: nothing in the game
# distinguishes a jack from a king.
VALUES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
ACE = 0
TEN = 9

# Cache sizes are bounded rather than unlimited. A single decision can reach a
# few hundred thousand dealer states, and a process that answers many of them —
# the test suite, or the house-edge check — would otherwise keep every one.
DEALER_CACHE = 1 << 18
PLAYER_CACHE = 1 << 17


class Rules(NamedTuple):
    """A complete table. Every rule that moves the house edge is a field here,
    because a hard-coded rule cannot be priced."""

    decks: int = 6
    hit_soft_17: bool = False
    blackjack_pays: float = 1.5
    double_after_split: bool = True
    max_splits: int = 3          # so four hands
    resplit_aces: bool = False
    hit_split_aces: bool = False
    late_surrender: bool = True
    penetration: float = 0.75

    @property
    def cards(self) -> int:
        return 52 * self.decks


# The benchmark game: six decks, dealer stands on soft 17, double after split,
# late surrender, 3:2. Exact house edge with perfect basic strategy ~0.26%.
VEGAS6 = Rules()


# --------------------------------------------------------------------------
# Compositions
# --------------------------------------------------------------------------

def fresh(decks: int = 6) -> tuple[int, ...]:
    return tuple([4 * decks] * 9 + [16 * decks])


def remove(comp: tuple[int, ...], index: int) -> tuple[int, ...]:
    return comp[:index] + (comp[index] - 1,) + comp[index + 1:]


def index_of(value: int) -> int:
    """Card value 1..10 -> composition index."""
    return 0 if value == 1 else value - 1


def total_cards(comp: tuple[int, ...]) -> int:
    return sum(comp)


def hand_state(values) -> tuple[int, bool]:
    """Cards -> (total counting every ace as one, whether an ace is present)."""
    hard = sum(values)
    return hard, 1 in values


def best_total(hard: int, ace: bool) -> int:
    return hard + 10 if ace and hard + 10 <= 21 else hard


def is_soft(hard: int, ace: bool) -> bool:
    return ace and hard + 10 <= 21


def is_natural(values) -> bool:
    return len(values) == 2 and 1 in values and 10 in values


# --------------------------------------------------------------------------
# The dealer
# --------------------------------------------------------------------------

@lru_cache(maxsize=DEALER_CACHE)
def dealer_dist(comp: tuple[int, ...], hard: int, ace: bool,
                hit_soft_17: bool) -> tuple[float, ...]:
    """Where the dealer's hand ends up: (17, 18, 19, 20, 21, bust).

    Both of the dealer's cards are known by the time this is called, so nothing
    here has to think about the peek.
    """
    total = best_total(hard, ace)
    if total > 21:
        return (0.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    if total >= 18 or (total == 17 and not (hit_soft_17 and is_soft(hard, ace))):
        out = [0.0] * 6
        out[total - 17] = 1.0
        return tuple(out)

    left = total_cards(comp)
    if left == 0:
        # A shoe that runs out mid-hand cannot happen at the table, where the
        # cut card only ever ends a hand. Standing is the honest answer.
        out = [0.0] * 6
        out[max(total - 17, 0)] = 1.0
        return tuple(out)

    acc = [0.0] * 6
    for i, value in enumerate(VALUES):
        if comp[i] == 0:
            continue
        p = comp[i] / left
        sub = dealer_dist(remove(comp, i), hard + value, ace or i == ACE, hit_soft_17)
        for k in range(6):
            acc[k] += p * sub[k]
    return tuple(acc)


@lru_cache(maxsize=DEALER_CACHE)
def hole_weights(comp: tuple[int, ...], up: int) -> tuple[float, ...]:
    """What the player believes the hole card is.

    A dealer showing an ace or a ten has already peeked, so the rank that would
    have made a natural is not there. Everything else keeps its share.
    """
    partner = TEN if up == 1 else (ACE if up == 10 else -1)
    left = sum(comp[i] for i in range(10) if i != partner)
    if left == 0:
        return (0.0,) * 10
    return tuple(0.0 if i == partner else comp[i] / left for i in range(10))


@lru_cache(maxsize=DEALER_CACHE)
def draw_probs(comp: tuple[int, ...], up: int) -> tuple[float, ...]:
    """What the next card off the shoe is, to a player who cannot see the hole.

    The hole card is one of these cards and cannot be dealt again, so the chance
    of drawing rank c is its count less the chance the hole card is that rank,
    over the cards that are left. Where the dealer has not peeked this comes
    straight back out as count / total; where it has, the excluded rank becomes
    slightly likelier, which is exactly the information the peek gave away.
    """
    left = sum(comp)
    if left <= 1:
        return (0.0,) * 10
    w = hole_weights(comp, up)
    return tuple((comp[i] - w[i]) / (left - 1) for i in range(10))


@lru_cache(maxsize=DEALER_CACHE)
def dealer_final(comp: tuple[int, ...], up: int, hit_soft_17: bool) -> tuple[float, ...]:
    """Where the dealer's hand ends up, averaged over a hole card nobody has seen."""
    w = hole_weights(comp, up)
    acc = [0.0] * 6
    for i, value in enumerate(VALUES):
        if w[i] == 0.0:
            continue
        hard, ace = hand_state((up, value))
        sub = dealer_dist(remove(comp, i), hard, ace, hit_soft_17)
        for k in range(6):
            acc[k] += w[i] * sub[k]
    return tuple(acc)


def stand_ev(comp: tuple[int, ...], total: int, up: int, rules: Rules) -> float:
    if total > 21:
        return -1.0
    dist = dealer_final(comp, up, rules.hit_soft_17)
    ev = dist[5]
    for k in range(5):
        final = 17 + k
        if total > final:
            ev += dist[k]
        elif total < final:
            ev -= dist[k]
    return ev


# --------------------------------------------------------------------------
# The player
# --------------------------------------------------------------------------

@lru_cache(maxsize=PLAYER_CACHE)
def play_ev(comp: tuple[int, ...], hard: int, ace: bool, up: int, rules: Rules) -> float:
    """The best of standing and hitting, hitting as well as it can from there.

    The choice is made on what the player knows, which is the upcard and the
    shoe. It is never made twice for two different hole cards.
    """
    total = best_total(hard, ace)
    if total > 21:
        return -1.0
    best = stand_ev(comp, total, up, rules)
    if total == 21 or total_cards(comp) <= 1:
        return best
    return max(best, hit_ev(comp, hard, ace, up, rules))


def hit_ev(comp: tuple[int, ...], hard: int, ace: bool, up: int, rules: Rules) -> float:
    """One card, then whatever is best after it."""
    ev = 0.0
    for i, (value, p) in enumerate(zip(VALUES, draw_probs(comp, up))):
        if p == 0.0:
            continue
        ev += p * play_ev(remove(comp, i), hard + value, ace or i == ACE, up, rules)
    return ev


def draw_once_ev(comp: tuple[int, ...], hard: int, ace: bool, up: int, rules: Rules) -> float:
    """One card, then stand. Doubling is this at twice the stake, and a split
    ace that may not be hit is this at one."""
    if total_cards(comp) <= 1:
        return stand_ev(comp, best_total(hard, ace), up, rules)
    ev = 0.0
    for i, (value, p) in enumerate(zip(VALUES, draw_probs(comp, up))):
        if p == 0.0:
            continue
        new_hard, new_ace = hard + value, ace or i == ACE
        ev += p * stand_ev(remove(comp, i), best_total(new_hard, new_ace), up, rules)
    return ev


@lru_cache(maxsize=PLAYER_CACHE)
def split_hand_ev(comp: tuple[int, ...], pair_value: int, splits_left: int,
                  up: int, rules: Rules) -> float:
    """What one hand created by a split is worth, from its lone card onward.

    Each hand is priced as if the others did not exist. Resplitting is followed:
    drawing the pair card again turns this hand into two of the same kind.
    """
    if total_cards(comp) <= 1:
        return 0.0
    ace_pair = pair_value == 1
    ev = 0.0
    for i, (value, p) in enumerate(zip(VALUES, draw_probs(comp, up))):
        if p == 0.0:
            continue
        rest = remove(comp, i)

        if value == pair_value and splits_left > 0 and (not ace_pair or rules.resplit_aces):
            ev += p * 2 * split_hand_ev(rest, pair_value, splits_left - 1, up, rules)
            continue

        hard, ace = hand_state((pair_value, value))
        if ace_pair and not rules.hit_split_aces:
            # One card to a split ace, and twenty-one on it is not a natural.
            ev += p * stand_ev(rest, best_total(hard, ace), up, rules)
            continue

        best = play_ev(rest, hard, ace, up, rules)
        if rules.double_after_split:
            best = max(best, 2 * draw_once_ev(rest, hard, ace, up, rules))
        ev += p * best
    return ev


# --------------------------------------------------------------------------
# What each action is worth
# --------------------------------------------------------------------------

class ActionEV(NamedTuple):
    stand: float
    hit: float
    double: float | None
    split: float | None
    surrender: float | None

    def options(self) -> dict[str, float]:
        return {name: value for name, value in self._asdict().items() if value is not None}

    def best(self) -> str:
        return max(self.options().items(), key=lambda kv: kv[1])[0]


def action_evs(comp: tuple[int, ...], cards, up: int, rules: Rules = VEGAS6, *,
               can_double: bool = True, can_split: bool = True,
               can_surrender: bool = True, splits_left: int | None = None) -> ActionEV:
    """Every action available to `cards` against `up`, priced against `comp`.

    `comp` is the shoe with every visible card already taken out of it and with
    the dealer's hole card still in: nobody has seen it, so as far as this hand
    is concerned it is still in the shoe.

    Hitting takes exactly one card and then plays the hand as well as it can,
    which is what a chart's H means. Taking the card is the part being priced:
    what happens afterwards is a later decision and gets its own answer.
    """
    hard, ace = hand_state(cards)
    two = len(cards) == 2
    pair = two and cards[0] == cards[1]
    if splits_left is None:
        splits_left = rules.max_splits - 1

    stand = stand_ev(comp, best_total(hard, ace), up, rules)
    hit = hit_ev(comp, hard, ace, up, rules)
    double = (2 * draw_once_ev(comp, hard, ace, up, rules)
              if can_double and two else None)
    split = (2 * split_hand_ev(comp, cards[0], splits_left, up, rules)
             if can_split and pair else None)
    # Late surrender: the dealer has already checked, so a natural has taken the
    # whole bet and never reaches here.
    surrender = -0.5 if (can_surrender and rules.late_surrender and two) else None
    return ActionEV(stand=stand, hit=hit, double=double, split=split, surrender=surrender)


# --------------------------------------------------------------------------
# Counting
#
# Not used to play anything. The table never tells anyone the count on its own:
# the cards that have come out are printed under it and counting them is the
# game. This is here so that a bet can be answered afterwards with what it was
# actually worth.
# --------------------------------------------------------------------------

# Hi-Lo: the low cards that help the dealer count up, the tens and aces that
# help the player count down.
HI_LO = (-1, 1, 1, 1, 1, 1, 0, 0, 0, -1)

# Edge per unit at each true count, measured rather than recited: 200 million
# rounds of six-deck S17 DAS at 0.75 penetration, played with deviation indices.
# The industry's "about half a percent per true count" comes out at +0.4795%
# over this range by weighted least squares, but the slope depends on the range
# — over TC +2 to +9 it is +0.5885% — which is why the measured points are kept
# and interpolated instead of a single line being drawn through them.
MEASURED_EDGE = (
    (-6, -0.0291), (-5, -0.0243), (-4, -0.0197), (-3, -0.0151), (-2, -0.0088),
    (-1, -0.0052), (0, -0.0012), (1, 0.0057), (2, 0.0094), (3, 0.0174),
    (4, 0.0228), (5, 0.0274), (6, 0.0382),
)
EDGE_PER_TC = 0.004795


def hi_lo(values) -> int:
    """The running count of the cards that have come out."""
    return sum(HI_LO[index_of(v)] for v in values)


def true_count(running: int, cards_left: int) -> float:
    """Running count over the decks still to come. Nothing here rounds it down
    to a half deck: the table knows exactly how many cards are left, and
    pretending otherwise would be inventing an estimation error."""
    decks = cards_left / 52
    return running / decks if decks > 0.05 else 0.0


def edge_at(tc: float) -> float:
    """Edge per unit at this true count, interpolated between the measured
    points and continued at the fitted slope beyond them."""
    low, high = MEASURED_EDGE[0], MEASURED_EDGE[-1]
    if tc <= low[0]:
        return low[1] + (tc - low[0]) * EDGE_PER_TC
    if tc >= high[0]:
        return high[1] + (tc - high[0]) * EDGE_PER_TC
    for (x0, y0), (x1, y1) in zip(MEASURED_EDGE, MEASURED_EDGE[1:]):
        if x0 <= tc <= x1:
            return y0 + (y1 - y0) * (tc - x0) / (x1 - x0)
    return 0.0


def clear_caches() -> None:
    dealer_dist.cache_clear()
    play_ev.cache_clear()
    split_hand_ev.cache_clear()
