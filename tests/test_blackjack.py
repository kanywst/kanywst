#!/usr/bin/env python3
"""
Tests for the table.

Nobody deals a hand here on purpose: the table is played by strangers clicking
links, and the first sign of a broken renderer is a broken image on the profile
or an Action that fails on someone else's click. These cover the settlement, the
one thing that must never appear in a public state file, the markup invariants
the table depends on to look like a table, and that every image the renderer can
name exists.

Most of them stack the shoe, because a hand that deals itself proves nothing
about what happens on a split ace.
"""

import contextlib
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import blackjack as bj  # noqa: E402

CARDS = ROOT / ".github" / "cards"


@contextlib.contextmanager
def stacked(*cards: str):
    """Deal these cards, in this order, instead of whatever the shoe would."""
    queue = list(cards)

    def deal(state, weights=None):
        card = queue.pop(0)
        state["shoe"]["seen"].append(card)
        return card

    with mock.patch.object(bj, "draw", deal):
        yield


@contextlib.contextmanager
def coin(value: float):
    """Fix the one coin flip in the game: whether the peek finds a natural."""
    class Fixed:
        @staticmethod
        def random():
            return value

        @staticmethod
        def choice(seq):
            return sorted(seq)[0]

    with mock.patch.object(bj, "RNG", Fixed):
        yield


def spot(cards, bet=2, **kw):
    hand = {"cards": list(cards), "bet": bet, "doubled": False, "done": False,
            "surrendered": False, "from_split": False}
    hand.update(kw)
    return hand


def table(up="7D", cards=("TH", "6C"), bet=2, phase="player", **kw):
    """A state sitting in the middle of a hand, without having played one."""
    state = bj.blank_state()
    state["hand"].update({
        "number": 7, "phase": phase, "bet": bet, "up": up,
        "peeked": phase == "player" and bj.value_of(up) in (1, 10),
        "hands": [spot(cards, bet)],
    })
    state["hand"].update(kw)
    state["shoe"]["seen"] = [up, *cards]
    return state


class Sandbox(unittest.TestCase):
    """Keep the repo's own README, state and log out of every test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self.tmp.name)
        readme = tmp / "README.md"
        readme.write_text(
            f"# t\n\n{bj.START_MARKER}\nWAS-HERE\n{bj.END_MARKER}\n", encoding="utf-8"
        )
        self._paths = (bj.README_PATH, bj.STATE_PATH, bj.LOG_PATH)
        bj.README_PATH = readme
        bj.STATE_PATH = tmp / "blackjack.json"
        bj.LOG_PATH = tmp / "blackjack-log.txt"

    def tearDown(self) -> None:
        bj.README_PATH, bj.STATE_PATH, bj.LOG_PATH = self._paths
        self.tmp.cleanup()


class Settlement(Sandbox):
    def test_a_natural_pays_three_to_two(self):
        state = bj.blank_state()
        with stacked("AS", "7D", "KH", "9C"):
            bj.play(state, "bet 2 1", "someone")
        self.assertEqual(state["result"], 3.0)
        self.assertEqual(state["recent"][0]["hands"][0]["result"], "blackjack")

    def test_a_natural_does_not_make_the_dealer_draw(self):
        # Burning cards nobody needed would move a count people are keeping.
        state = bj.blank_state()
        with stacked("AS", "7D", "KH", "9C"):
            bj.play(state, "bet 2 1", "someone")
        self.assertEqual(state["shoe"]["seen"], ["AS", "7D", "KH", "9C"])

    def test_busting_loses_the_bet_and_the_dealer_stays_put(self):
        state = table()
        with stacked("9S", "TD"):
            bj.play(state, "hit 7", "someone")
        self.assertEqual(state["result"], -2.0)
        self.assertEqual(state["recent"][0]["hands"][0]["result"], "bust")
        self.assertEqual(len(state["recent"][0]["dealer"]), 2)

    def test_surrender_gives_up_half(self):
        state = table()
        with stacked("TD"):
            bj.play(state, "surrender 7", "someone")
        self.assertEqual(state["result"], -1.0)

    def test_doubling_takes_one_card_and_stops(self):
        state = table(cards=("6H", "5C"))
        with stacked("9S", "TD"):
            bj.play(state, "double 7", "someone")
        played = state["recent"][0]["hands"][0]
        self.assertEqual(played["cards"], ["6H", "5C", "9S"])
        self.assertEqual(state["result"], 4.0)   # twenty against the dealer's seventeen

    def test_a_push_is_a_push(self):
        state = table(up="TS", cards=("TH", "TD"))
        with stacked("TC"):
            bj.play(state, "stand 7", "someone")
        self.assertEqual(state["result"], 0.0)
        self.assertEqual(state["recent"][0]["hands"][0]["result"], "push")

    def test_the_dealer_stands_on_soft_seventeen(self):
        state = table(up="AS", cards=("TH", "9C"))
        with stacked("6D"):
            bj.play(state, "stand 7", "someone")
        self.assertEqual(state["recent"][0]["dealer"], ["AS", "6D"])
        self.assertEqual(state["result"], 2.0)


class Splitting(Sandbox):
    def test_a_split_makes_two_hands_and_deals_to_each(self):
        state = table(cards=("8S", "8D"))
        with stacked("3H"):
            bj.play(state, "split 7", "someone")
        hands = state["hand"]["hands"]
        self.assertEqual([h["cards"] for h in hands], [["8S", "3H"], ["8D"]])
        self.assertEqual(state["hand"]["active"], 0)
        # Standing on the first hand brings the second one into play, and it
        # draws as it arrives. It does not end the round.
        with stacked("TD"):
            bj.play(state, "stand 7", "someone")
        self.assertEqual(state["hand"]["active"], 1)
        self.assertEqual(state["hand"]["hands"][1]["cards"], ["8D", "TD"])
        with stacked("9C", "KS"):
            bj.play(state, "stand 7", "someone")
        # The dealer turned over sixteen and went bust, so both hands are paid.
        self.assertEqual(state["result"], 4.0)

    def test_a_split_ace_gets_one_card_and_no_say(self):
        state = table(cards=("AS", "AD"))
        with stacked("9H", "TC", "2S", "TD"):
            bj.play(state, "split 7", "someone")
        played = state["recent"][0]["hands"]
        self.assertEqual([h["cards"] for h in played], [["AS", "9H"], ["AD", "TC"]])

    def test_twenty_one_on_a_split_is_not_a_natural(self):
        # Two aces split into two twenty-ones against the dealer's twenty. They
        # are paid at even money, not at three to two: four units, not six.
        state = table(up="TS", cards=("AS", "AD"))
        with stacked("KH", "KD", "TC"):
            bj.play(state, "split 7", "someone")
        played = state["recent"][0]["hands"]
        self.assertEqual([h["result"] for h in played], ["won", "won"])
        self.assertEqual(state["result"], 4.0)

    def test_the_fourth_hand_is_the_last(self):
        state = table(cards=("8S", "8D"), hands=[
            spot(["8S", "8D"]), spot(["8H"], from_split=True),
            spot(["8C"], from_split=True), spot(["9S"], from_split=True),
        ])
        self.assertFalse(bj.options(state)["split"])


class Insurance(Sandbox):
    def test_it_is_offered_on_an_ace_and_nothing_else(self):
        state = bj.blank_state()
        with stacked("TH", "AS", "6C"):
            bj.play(state, "bet 2 1", "someone")
        self.assertEqual(state["hand"]["phase"], "insurance")

    def test_it_pays_two_to_one_when_the_dealer_has_it(self):
        state = table(up="AS", phase="insurance")
        with coin(0.0), stacked("KD"):
            bj.play(state, "ins yes 7", "someone")
        # Two units on the hand, one on insurance: the hand loses and the
        # insurance pays two, so the round is flat.
        self.assertEqual(state["result"], 0.0)

    def test_declining_it_loses_the_hand_and_nothing_else(self):
        state = table(up="AS", phase="insurance")
        with coin(0.0), stacked("KD"):
            bj.play(state, "ins no 7", "someone")
        self.assertEqual(state["result"], -2.0)

    def test_even_money_is_the_same_bet_by_another_name(self):
        state = table(up="AS", cards=("KH", "AD"), phase="insurance")
        with coin(0.99), stacked("7C"):
            bj.play(state, "ins yes 7", "someone")
        # A natural insured against a dealer who did not have one: three on the
        # blackjack, one lost on the insurance.
        self.assertEqual(state["result"], 2.0)

    def test_taking_it_is_a_mistake_that_is_priced(self):
        state = table(up="AS", phase="insurance")
        with coin(0.99), stacked("7C"):
            bj.play(state, "ins yes 7", "someone")
        self.assertLess(state["coach"]["cost"], 0)


class Secrets(Sandbox):
    """The state file is public. What is in it is what anyone can read before
    they decide how to play."""

    def test_the_hole_card_is_not_in_the_state_until_it_is_turned_over(self):
        state = bj.blank_state()
        with stacked("TH", "9D", "6C"):
            bj.play(state, "bet 2 1", "someone")
        bj.save_state(state)
        written = bj.STATE_PATH.read_text(encoding="utf-8")
        self.assertIsNone(state["hand"]["hole"])
        # Three cards are on the table and three cards have left the shoe.
        self.assertEqual(len(state["shoe"]["seen"]), 3)
        self.assertNotIn('"hole": "', written)

    def test_nothing_is_drawn_for_a_dealer_who_has_not_looked(self):
        state = table(up="7D")
        with stacked("2H"):
            bj.play(state, "hit 7", "someone")
        # The card that came out was the player's, not the dealer's.
        self.assertEqual(state["hand"]["hands"][0]["cards"][-1], "2H")
        self.assertIsNone(state["hand"]["hole"])

    def test_a_peek_that_finds_nothing_still_draws_nothing(self):
        state = bj.blank_state()
        with coin(0.99), stacked("TH", "TS", "6C"):
            bj.play(state, "bet 2 1", "someone")
        self.assertEqual(state["hand"]["phase"], "player")
        self.assertTrue(state["hand"]["peeked"])
        self.assertIsNone(state["hand"]["hole"])
        self.assertEqual(len(state["shoe"]["seen"]), 3)


class Clicks(Sandbox):
    def test_a_stale_link_is_refused(self):
        state = table()
        message = bj.play(state, "hit 6", "someone")
        self.assertIn("Someone got there first", message)
        self.assertEqual(state["hand"]["hands"][0]["cards"], ["TH", "6C"])

    def test_a_bet_during_a_hand_is_refused(self):
        state = table()
        message = bj.play(state, "bet 5 7", "someone")
        self.assertIn("Play it out first", message)

    def test_an_action_before_the_deal_is_refused(self):
        state = bj.blank_state()
        self.assertIn("Put a chip out", bj.play(state, "hit 1", "someone"))

    def test_the_insurance_question_comes_first(self):
        state = table(up="AS", phase="insurance")
        self.assertIn("insurance", bj.play(state, "hit 7", "someone").lower())

    def test_parse_takes_the_documented_commands_and_nothing_else(self):
        for title in ["bj|bet 5 12", "bj | hit 3", "bj|ins yes 9", "bj|surrender 100"]:
            with self.subTest(title):
                self.assertIsNotNone(bj.parse(title))
        for title in ["bj|bet 3 12", "bj|hit", "bj|fold 3", "shogi|sel 7g", "",
                      "bj|bet 5", "bj|ins maybe 9"]:
            with self.subTest(title):
                self.assertIsNone(bj.parse(title))

    def test_a_hand_that_never_reaches_a_decision_still_counts_its_player(self):
        # A natural settles from the deal, so nothing on that path goes through
        # the coach. The ceiling on the public state file has to hold anyway.
        state = bj.blank_state()
        state["players"] = {f"p{i}": {"hands": 1, "decisions": 1, "cost": 0.0}
                            for i in range(bj.MAX_PLAYERS)}
        with stacked("AS", "7D", "KH", "9C"):
            bj.play(state, "bet 2 1", "newcomer")
        self.assertEqual(len(state["players"]), bj.MAX_PLAYERS)
        self.assertIn("newcomer", state["players"])
        self.assertEqual(state["players"]["newcomer"]["hands"], 1)

    def test_the_coach_charges_nothing_for_the_best_action(self):
        state = table(up="9D", cards=("TH", "6C"))
        with stacked("TD"):
            bj.play(state, "surrender 7", "someone")
        self.assertEqual(state["coach"]["cost"], 0.0)
        self.assertEqual(state["players"]["someone"]["decisions"], 1)

    def test_the_coach_charges_for_a_worse_one(self):
        state = table(up="9D", cards=("TH", "6C"))
        with stacked("TD"):
            bj.play(state, "stand 7", "someone")
        self.assertLess(state["coach"]["cost"], -0.01)


class Shoe(Sandbox):
    def test_it_is_shuffled_at_the_cut_card_and_not_before(self):
        cut = round(bj.RULES.cards * bj.RULES.penetration)
        deck = bj.full_shoe(bj.RULES.decks)

        state = table()
        state["shoe"]["seen"] = deck[:cut - 8]
        with stacked("TD"):
            bj.play(state, "stand 7", "someone")
        self.assertEqual(state["shoe"]["number"], 1)

        state = table()
        state["shoe"]["seen"] = deck[:cut - 1]
        with stacked("TD"):
            bj.play(state, "stand 7", "someone")
        self.assertEqual(state["shoe"]["number"], 2)
        self.assertEqual(state["shoe"]["seen"], [])
        self.assertIn("shoe 1 closed", bj.LOG_PATH.read_text(encoding="utf-8"))

    def test_no_card_is_dealt_more_often_than_it_exists(self):
        state = bj.blank_state()
        for _ in range(120):
            hand = state["hand"]
            if hand["phase"] == "betting":
                command = f"bet 1 {hand['number']}"
            elif hand["phase"] == "insurance":
                command = f"ins no {hand['number']}"
            else:
                command = f"stand {hand['number']}"
            bj.play(state, command, "someone")
            self.assertTrue(all(n >= 0 for n in bj.remaining(state).values()))
            self.assertTrue(all(n >= 0 for n in bj.composition(state)))


class Markup(Sandbox):
    def rendered(self, state) -> str:
        return bj.render(state)

    def test_every_image_the_renderer_names_exists(self):
        states = [
            table(),
            table(up="AS", phase="insurance"),
            table(cards=("8S", "3H"), hands=[spot(["8S", "3H"]), spot(["8D", "2C"])]),
            bj.blank_state(),
        ]
        for state in states:
            for name in re.findall(r"/cards/([^.]+)\.svg", self.rendered(state)):
                with self.subTest(name):
                    self.assertTrue((CARDS / f"{name}.svg").exists())

    def test_no_size_attributes_and_every_image_aligned_top(self):
        # A sized image is given a 6px border radius and a background of
        # GitHub's choosing, which turns the felt into a row of rounded tiles.
        html = self.rendered(table())
        for tag in re.findall(r"<img[^>]*>", html):
            with self.subTest(tag):
                self.assertNotIn("width=", tag)
                self.assertNotIn("height=", tag)
                self.assertIn('align="top"', tag)

    def test_every_image_is_inside_a_link_of_our_own(self):
        # Without one, GitHub wraps the image in a link to the raw SVG and a
        # visitor clicking the felt opens a .svg file.
        html = self.rendered(table())
        self.assertNotIn("<img", re.sub(r'<a href="[^"]+"><img[^>]*></a>', "", html))

    def test_the_rows_are_all_one_width(self):
        state = table(cards=("8S", "3H", "9C"),
                      hands=[spot(["8S", "3H", "9C"]), spot(["8D", "2C"])])
        rows = re.findall(r"<pre>(.*?)</pre>", self.rendered(state))
        widths = {row.count("<img") for row in rows[:3]}
        self.assertEqual(len(widths), 1, "a staggered row means a staggered table")

    def test_nothing_can_end_the_raw_html_block(self):
        html = self.rendered(table())
        self.assertNotIn("<!--", html)
        self.assertNotIn(bj.END_MARKER, html)

    def test_write_readme_only_touches_its_own_block(self):
        before = bj.README_PATH.read_text(encoding="utf-8")
        bj.write_readme(table())
        after = bj.README_PATH.read_text(encoding="utf-8")
        self.assertEqual(before.split(bj.START_MARKER)[0], after.split(bj.START_MARKER)[0])
        self.assertEqual(before.split(bj.END_MARKER)[1], after.split(bj.END_MARKER)[1])
        self.assertNotIn("WAS-HERE", after)

    def test_the_table_is_drawn_before_a_card_is_out(self):
        html = self.rendered(bj.blank_state())
        self.assertIn("slot.svg", html)
        self.assertIn("chip1.svg", html)

    def test_the_hands_played_recently_are_shown(self):
        state = bj.blank_state()
        state["recent"] = [{
            "number": 3, "bet": 2,
            "hands": [{"cards": ["TH", "6C", "8S"], "result": "bust"}],
            "dealer": ["TS", "7D"], "dealer_total": 17, "insurance": 0, "net": -2,
        }]
        html = self.rendered(state)
        self.assertIn("24 bust (T 6 8)", html)
        self.assertIn("17 (T 7)", html)
        self.assertIn("-2u", html)


if __name__ == "__main__":
    unittest.main()
