#!/usr/bin/env python3
"""
Tests for the exact calculator.

The calculator is the only thing on the table that cannot be checked by looking
at it. A board renders wrong and you see it; an expected value renders wrong and
it just quietly tells strangers that the worse action was better. So it is
checked three ways.

  1. Against an independent Monte Carlo, which deals a real shuffled shoe with a
     physical hole card and rejection sampling for the peek. It shares no code
     with the calculator, so agreement is evidence.
  2. Against the published basic strategy chart in tests/data/basic-strategy.txt.
     Every cell has to fall out of the numbers, from a full shoe, with nobody
     having told the calculator what the chart says.
  3. Against its own past answers, so a change that moves a number has to be
     deliberate.

The full 260-cell chart takes about two and a half minutes, and the Monte Carlo
is only worth running long, so both are behind BJ_SLOW=1, which CI sets. Without
it the chart check does ten cells and the simulation runs short.
"""

import os
import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import bjmath as m  # noqa: E402

SLOW = os.environ.get("BJ_SLOW") == "1"
CHART = ROOT / "tests" / "data" / "basic-strategy.txt"
UPS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 1)


def shoe_without(cards, up, decks=6):
    """A full shoe with the visible cards taken out. The hole card stays in it:
    nobody has seen it, so it is still a card the player could draw."""
    comp = m.fresh(decks)
    for value in list(cards) + [up]:
        comp = m.remove(comp, m.index_of(value))
    return comp


def hand_of(name: str) -> tuple[int, ...]:
    """'hard 16' -> (9, 7), 'soft 18' -> (1, 7), 'pair 8' -> (8, 8)."""
    kind, what = name.split()
    if kind == "pair":
        value = 1 if what == "A" else (10 if what == "T" else int(what))
        return (value, value)
    total = int(what)
    if kind == "soft":
        return (1, total - 11)
    # Built without a ten wherever possible, as the chart's header says.
    first = min(9, total - 2)
    return (first, total - first)


def decide(name: str, up: int) -> str:
    cards = hand_of(name)
    ev = m.action_evs(shoe_without(cards, up), cards, up)
    options = ev.options()
    best = max(options.items(), key=lambda kv: kv[1])[0]
    if best == "double":
        # A chart writes Ds where doubling is best but standing beats hitting,
        # because the fallback matters when the money is not there.
        return "D" if options["hit"] > options["stand"] else "Ds"
    return {"stand": "S", "hit": "H", "split": "P", "surrender": "R"}[best]


def published_chart() -> dict[str, list[str]]:
    rows = {}
    for line in CHART.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 12 and parts[0] in ("hard", "soft", "pair"):
            rows[f"{parts[0]} {parts[1]}"] = parts[2:]
    return rows


# --------------------------------------------------------------------------
# An independent simulation. Nothing below this line imports the calculator's
# idea of anything except the rules.
# --------------------------------------------------------------------------

def total_of(values) -> int:
    hard = sum(values)
    return hard + 10 if 1 in values and hard + 10 <= 21 else hard


def simulate(comp, up, player, action, trials, rng, rules=m.VEGAS6):
    """Mean and standard error of `action`, dealt from a real shoe.

    action is 'stand', 'double' (one card, then stand) or 'to17' (draw while
    under seventeen). Nothing here needs a strategy, which is the point: the
    three of them can be checked without agreeing on what is best.
    """
    cards = []
    for i, value in enumerate(m.VALUES):
        cards.extend([value] * comp[i])

    total = squares = 0.0
    for _ in range(trials):
        while True:
            rng.shuffle(cards)
            hole = cards[0]
            # The peek: a hole card that would have ended the round means this
            # deal never reached a decision, so it is not one of the deals the
            # number describes.
            if up in (1, 10) and total_of([up, hole]) == 21:
                continue
            break

        hand, k = list(player), 1
        if action == "double":
            hand.append(cards[k])
            k += 1
        elif action == "to17":
            while total_of(hand) < 17:
                hand.append(cards[k])
                k += 1

        player_total = total_of(hand)
        if player_total > 21:
            value = -1.0
        else:
            dealer = [up, hole]
            while True:
                t = total_of(dealer)
                soft = 1 in dealer and sum(dealer) + 10 <= 21
                if t > 21 or t > 17 or (t == 17 and not (rules.hit_soft_17 and soft)):
                    break
                dealer.append(cards[k])
                k += 1
            dealer_total = total_of(dealer)
            if dealer_total > 21 or player_total > dealer_total:
                value = 1.0
            elif player_total < dealer_total:
                value = -1.0
            else:
                value = 0.0
        if action == "double":
            value *= 2
        total += value
        squares += value * value

    mean = total / trials
    variance = squares / trials - mean * mean
    return mean, (variance / trials) ** 0.5


class Dealer(unittest.TestCase):
    def test_the_distribution_is_a_distribution(self):
        for up in UPS:
            with self.subTest(up=up):
                dist = m.dealer_final(m.fresh(6), up, False)
                self.assertAlmostEqual(sum(dist), 1.0, places=12)
                self.assertTrue(all(p >= 0 for p in dist))

    def test_a_standing_hand_is_where_it_stands(self):
        for total in range(17, 22):
            with self.subTest(total=total):
                dist = m.dealer_dist(m.fresh(6), total, False, False)
                self.assertEqual(dist[total - 17], 1.0)

    def test_soft_seventeen_is_where_the_rule_shows(self):
        stands = m.dealer_dist(m.fresh(6), 7, True, False)
        hits = m.dealer_dist(m.fresh(6), 7, True, True)
        self.assertEqual(stands[0], 1.0)
        self.assertLess(hits[0], 1.0)

    def test_the_peek_takes_the_natural_out(self):
        # Showing an ace, the dealer has looked and has no ten under it. So the
        # hand can no longer be twenty-one in two cards.
        weights = m.hole_weights(m.fresh(6), 1)
        self.assertEqual(weights[m.TEN], 0.0)
        self.assertAlmostEqual(sum(weights), 1.0, places=12)
        self.assertEqual(m.hole_weights(m.fresh(6), 10)[m.ACE], 0.0)
        # Nothing is excluded when the dealer had no reason to look.
        self.assertTrue(all(w > 0 for w in m.hole_weights(m.fresh(6), 6)))

    def test_the_peek_tilts_the_player_draw_the_other_way(self):
        # The hole card is one of the cards left and cannot be dealt again. Told
        # it is not a ten, the player is that much likelier to draw one.
        comp = m.fresh(6)
        probs = m.draw_probs(comp, 1)
        self.assertAlmostEqual(sum(probs), 1.0, places=12)
        self.assertGreater(probs[m.TEN], comp[m.TEN] / sum(comp))
        # With no peek it is just the shoe.
        plain = m.draw_probs(comp, 6)
        for i in range(10):
            self.assertAlmostEqual(plain[i], comp[i] / sum(comp), places=12)


class AgainstSimulation(unittest.TestCase):
    """The check that would have caught the calculator looking at the hole card:
    knowing it is worth about a quarter of a unit on sixteen, and the simulation
    does not know it either."""

    def check(self, cards, up, action, exact, trials, seed):
        comp = shoe_without(cards, up)
        mean, se = simulate(comp, up, cards, action, trials, random.Random(seed))
        sigmas = abs(mean - exact) / se
        self.assertLess(sigmas, 4.0,
                        f"{cards} v {up} {action}: exact {exact:+.5f}, "
                        f"simulated {mean:+.5f} +-{se:.5f} ({sigmas:.1f} sigma)")

    def test_standing(self):
        trials = 200_000 if SLOW else 25_000
        for cards, up, seed in [((10, 6), 10, 1), ((1, 7), 4, 2), ((10, 10), 6, 3)]:
            with self.subTest(cards=cards, up=up):
                hard, ace = m.hand_state(cards)
                exact = m.stand_ev(shoe_without(cards, up), m.best_total(hard, ace),
                                   up, m.VEGAS6)
                self.check(cards, up, "stand", exact, trials, seed)

    def test_doubling(self):
        trials = 200_000 if SLOW else 25_000
        for cards, up, seed in [((5, 6), 10, 4), ((1, 7), 4, 5)]:
            with self.subTest(cards=cards, up=up):
                hard, ace = m.hand_state(cards)
                exact = 2 * m.draw_once_ev(shoe_without(cards, up), hard, ace, up, m.VEGAS6)
                self.check(cards, up, "double", exact, trials, seed)

    def test_drawing(self):
        # A policy both sides can follow, so the drawing machinery is checked
        # without the two of them having to agree on what is best.
        def to17(comp, hard, ace, up):
            total = m.best_total(hard, ace)
            if total > 21:
                return -1.0
            if total >= 17:
                return m.stand_ev(comp, total, up, m.VEGAS6)
            ev = 0.0
            for i, (value, p) in enumerate(zip(m.VALUES, m.draw_probs(comp, up))):
                if p:
                    ev += p * to17(m.remove(comp, i), hard + value, ace or i == m.ACE, up)
            return ev

        trials = 200_000 if SLOW else 25_000
        for cards, up, seed in [((10, 6), 10, 6), ((10, 2), 4, 7), ((9, 7), 1, 8)]:
            with self.subTest(cards=cards, up=up):
                hard, ace = m.hand_state(cards)
                exact = to17(shoe_without(cards, up), hard, ace, up)
                self.check(cards, up, "to17", exact, trials, seed)


class AgainstTheChart(unittest.TestCase):
    def test_the_famous_cells(self):
        # Ten cells nobody guesses right: the ones that are counterintuitive,
        # the ones that only hold under this rule set, and the two the
        # calculator got wrong while it was being written.
        cells = [
            ("hard 12", 4, "S"),    # stand on twelve, because the four busts more often
            ("hard 16", 9, "R"),
            ("hard 16", 7, "H"),
            ("hard 11", 1, "H"),    # only because the dealer stands on soft 17
            ("hard 10", 10, "H"),
            ("soft 18", 3, "Ds"),
            ("soft 18", 9, "H"),
            ("pair 8", 10, "P"),    # split into a ten, twice, and it is still better
            ("pair 9", 7, "S"),
            ("pair 4", 5, "P"),     # only because a split hand may be doubled
        ]
        for name, up, want in cells:
            with self.subTest(hand=name, up=up):
                self.assertEqual(decide(name, up), want)

    @unittest.skipUnless(SLOW, "set BJ_SLOW=1")
    def test_every_cell(self):
        for name, row in published_chart().items():
            for up, want in zip(UPS, row):
                with self.subTest(hand=name, up=up):
                    self.assertEqual(decide(name, up), want)


class Numbers(unittest.TestCase):
    """What the calculator said last time. Checked by the two classes above, so
    a change here is either an improvement or a bug, and never a surprise."""

    GOLDEN = {
        ((9, 7), 10): {"stand": -0.536809, "hit": -0.535392, "surrender": -0.500000},
        ((10, 6), 10): {"stand": -0.540954, "hit": -0.534676},
        ((5, 6), 10): {"hit": 0.118582, "double": 0.178452},
        ((1, 7), 4): {"stand": 0.180238, "hit": 0.124398, "double": 0.248797},
        ((8, 8), 10): {"split": -0.474798},
        ((1, 1), 10): {"split": 0.181988},
        ((10, 2), 4): {"stand": -0.211115, "hit": -0.210364},
    }

    def test_the_numbers_have_not_moved(self):
        for (cards, up), want in self.GOLDEN.items():
            ev = m.action_evs(shoe_without(cards, up), cards, up)
            for action, value in want.items():
                with self.subTest(cards=cards, up=up, action=action):
                    self.assertAlmostEqual(ev.options()[action], value, places=6)

    def test_the_same_total_from_different_cards_is_not_the_same_hand(self):
        # Twelve against a four: the chart says stand, and it is right for the
        # nine-three that the chart was drawn from. Ten-two is the other way,
        # by less than a thousandth of a unit. This is the whole reason the
        # calculator works in compositions.
        self.assertEqual(decide("hard 12", 4), "S")
        cards = (10, 2)
        ev = m.action_evs(shoe_without(cards, 4), cards, 4)
        self.assertGreater(ev.hit, ev.stand)
        self.assertLess(ev.hit - ev.stand, 0.002)

    def test_surrender_is_half_a_bet_and_only_on_two_cards(self):
        ev = m.action_evs(shoe_without((10, 6), 10), (10, 6), 10)
        self.assertEqual(ev.surrender, -0.5)
        drawn = m.action_evs(shoe_without((10, 4, 2), 10), (10, 4, 2), 10)
        self.assertIsNone(drawn.surrender)
        self.assertIsNone(drawn.double)
        self.assertEqual(set(drawn.options()), {"stand", "hit"})


if __name__ == "__main__":
    unittest.main()
