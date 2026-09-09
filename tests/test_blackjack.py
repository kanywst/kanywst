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
import json
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


def settled(by=("someone",), **kw):
    """A table between hands, with the hand that just ended still on the felt."""
    state = bj.blank_state()
    state["hand"] = bj.blank_hand(8)
    entry = {
        "number": 7, "bet": 10,
        "hands": [{"cards": ["8D", "3H", "4C"], "result": "lost"}],
        "dealer": ["2H", "2C", "5S", "KD"], "dealer_total": 19,
        "insurance": 0, "net": -20.0, "by": list(by),
    }
    entry.update(kw)
    state["recent"] = [entry]
    state["hands_played"] = 1
    state["result"] = -20.0
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


class StateFile(Sandbox):
    """The file is public, editable by hand, and read again on every click. A
    hand that comes back malformed must cost one hand, not the table."""

    def test_a_hand_whose_names_are_not_names_is_dealt_again(self):
        stored = bj.blank_state()
        stored["hand"]["number"] = 12
        stored["hand"]["by"] = [123]
        bj.STATE_PATH.write_text(json.dumps(stored), encoding="utf-8")
        state = bj.load_state()
        self.assertEqual(state["hand"]["by"], [])
        self.assertEqual(state["hand"]["number"], 1)

    def test_a_name_that_is_not_a_string_is_not_drawn(self):
        # The settled hands are only checked as a list, so the renderer is the
        # thing that has to hold: a row that raises takes down write_readme.
        state = settled(by=(123, "kanywst"))
        row = "\n".join(bj.recent_table(state))
        self.assertIn("@kanywst", row)
        self.assertNotIn("123", row)
        self.assertIn("@kanywst had 15", bj.headline(state))

    def test_a_settled_hand_whose_names_are_not_a_list_is_drawn_anyway(self):
        # A string would otherwise be iterated one character at a time, and a
        # number would raise where the table is being drawn.
        for by in ("kanywst", 123, None, {"kanywst": 1}):
            with self.subTest(by=by):
                state = settled()
                state["recent"][0]["by"] = by
                row = "\n".join(bj.recent_table(state))
                self.assertNotIn("@", row)
                self.assertIn("you had 15", bj.headline(state))


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


class LogFile(Sandbox):
    """The log is the only file here that is trimmed rather than rewritten, and
    the trim runs for the first time about two thousand hands in. Nobody would
    notice it going wrong until the whole file was already unreadable."""

    def close_shoes(self, count: int) -> str:
        state = bj.blank_state()
        for number in range(1, count + 1):
            state["shoe"] = {"seen": ["TH", "5C", "AS"] * 4, "number": number}
            bj.log_shoe(state)
        return bj.LOG_PATH.read_text(encoding="utf-8")

    def test_the_oldest_shoes_fall_off_and_the_rest_stay_readable(self):
        text = self.close_shoes(bj.MAX_LOG_SHOES + 5)
        self.assertTrue(text.startswith(bj.header()))
        kept = [line for line in text.splitlines() if line.startswith("  shoe ")]
        self.assertEqual(len(kept), bj.MAX_LOG_SHOES)
        # The ones kept are the newest, in order, and each still has its cards.
        numbers = [int(line.split()[1]) for line in kept]
        self.assertEqual(numbers, list(range(6, bj.MAX_LOG_SHOES + 6)))
        self.assertEqual(text.count("T 5 A T 5 A T 5 A T 5 A"), bj.MAX_LOG_SHOES)

    def test_nothing_is_thrown_away_before_the_limit(self):
        text = self.close_shoes(bj.MAX_LOG_SHOES)
        self.assertEqual(text.count("\n  shoe "), bj.MAX_LOG_SHOES)

    def test_the_log_says_who_played_the_hand(self):
        # The table shows three hands; everything before them is only here.
        state = table(up="2H", cards=("8D", "3H"), bet=10)
        with stacked("2C", "5S", "KD"):
            bj.play(state, "stand 7", "kanywst")
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertTrue(line.endswith("|  @kanywst"), line)
        self.assertIn("dealer 2 2 5 K 19", line)

    def test_a_hand_with_no_name_on_it_leaves_no_column_behind(self):
        state = table(up="2H", cards=("8D", "3H"), bet=10,
                      hands=[spot(["8D", "3H"], result="lost")])
        state["hand"]["by"] = []
        bj.append_log(state, -10.0, ["2H", "2C", "5S", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertTrue(line.endswith("-10u"), line)

    def test_every_name_on_a_hand_reaches_the_log(self):
        # The row has room for two; the record keeps all of them.
        state = table(up="2H", cards=("8D", "3H"), bet=10,
                      hands=[spot(["8D", "3H"], result="lost")],
                      by=["first", "second", "third"])
        bj.append_log(state, -10.0, ["2H", "2C", "5S", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertTrue(line.endswith("@first @second @third"), line)

    def test_a_doubled_hand_says_what_it_had_riding(self):
        # The chip that went down was ten and the hand cost twenty. A row that
        # only shows the chip reads like the table pays a loss at two to one.
        state = table(up="2H", cards=("8D", "3H", "4C"), bet=10,
                      hands=[spot(["8D", "3H", "4C"], bet=20, doubled=True,
                                  result="lost")])
        bj.append_log(state, -20.0, ["2H", "2C", "5S", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertIn("10->20u", line)

    def test_a_split_counts_every_chip_on_the_felt(self):
        state = table(up="2H", cards=("8D", "8H"), bet=10,
                      hands=[spot(["8D", "3H"], bet=10, result="lost"),
                             spot(["8H", "4C"], bet=10, result="lost")])
        bj.append_log(state, -20.0, ["2H", "2C", "5S", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertIn("10->20u", line)

    def test_a_hand_that_stayed_at_its_chip_shows_one_number(self):
        state = table(up="2H", cards=("8D", "3H"), bet=10,
                      hands=[spot(["8D", "3H"], bet=10, result="lost")])
        bj.append_log(state, -10.0, ["2H", "2C", "5S", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertIn("10u  8 3 11 lost", line)
        self.assertNotIn("->", line)

    def test_insurance_gets_its_own_field_when_it_was_taken(self):
        # Ten on the hand and five on the hole card: the hand loses both, and
        # -15u on a row that only says 10u is a result nobody can check.
        state = table(up="AS", cards=("8D", "3H"), bet=10, insurance=5.0,
                      hands=[spot(["8D", "3H"], bet=10, result="lost")])
        bj.append_log(state, -15.0, ["AS", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertIn("|  ins 5u  |  -15u", line)

    def test_a_hand_that_declined_insurance_carries_no_field_for_it(self):
        state = table(up="2H", cards=("8D", "3H"), bet=10,
                      hands=[spot(["8D", "3H"], bet=10, result="lost")])
        bj.append_log(state, -10.0, ["2H", "2C", "5S", "KD"])
        line = bj.LOG_PATH.read_text(encoding="utf-8").rstrip("\n").split("\n")[-1]
        self.assertNotIn("ins", line)

    def test_the_hands_and_the_shoes_share_the_file_without_confusing_it(self):
        # A hand line must never look like the start of a shoe to the trim.
        state = table()
        with stacked("TD"):
            bj.play(state, "stand 7", "someone")
        state["shoe"] = {"seen": ["TH", "5C"], "number": 1}
        bj.log_shoe(state)
        text = bj.LOG_PATH.read_text(encoding="utf-8")
        self.assertEqual(text.count("\n  shoe "), 1)
        self.assertIn("dealer", text)


class Log(unittest.TestCase):
    def test_the_log_in_the_repo_starts_the_way_the_script_writes_it(self):
        # The committed file is a seed, so that the workflow's `git add` always
        # has something to add. Nothing else keeps the two texts together.
        committed = (ROOT / ".github" / "blackjack-log.txt").read_text(encoding="utf-8")
        self.assertTrue(committed.startswith(bj.header()))

class Counting(Sandbox):
    def test_the_running_count_is_hi_lo(self):
        import bjmath
        self.assertEqual(bjmath.hi_lo([2, 3, 4, 5, 6]), 5)
        self.assertEqual(bjmath.hi_lo([7, 8, 9]), 0)
        self.assertEqual(bjmath.hi_lo([10, 1]), -2)
        # A full shoe counts to nothing, which is the whole point of the tags.
        self.assertEqual(bjmath.hi_lo([v for v in range(1, 10)] * 4 + [10] * 16), 0)

    def test_the_edge_follows_the_measured_points(self):
        import bjmath
        for tc, edge in bjmath.MEASURED_EDGE:
            with self.subTest(tc=tc):
                self.assertAlmostEqual(bjmath.edge_at(tc), edge, places=9)
        # And keeps going in the right direction past the ends of the table.
        self.assertLess(bjmath.edge_at(-9), bjmath.edge_at(-6))
        self.assertGreater(bjmath.edge_at(12), bjmath.edge_at(6))
        self.assertLess(bjmath.edge_at(0), 0)

    def test_the_bet_is_answered_with_what_it_was_worth(self):
        state = bj.blank_state()
        # A shoe stripped of its low cards is a shoe worth betting into.
        state["shoe"]["seen"] = ["5C", "6D", "4H", "3S", "2C"] * 12
        with stacked("TH", "7D", "9C", "8S"):
            message = bj.play(state, "bet 25 1", "someone")
        self.assertIn("running count was +60", message)
        self.assertIn("true count", message)
        self.assertIn("units before a card came out", message)

    def test_the_table_says_nothing_about_the_count_before_the_bet(self):
        state = bj.blank_state()
        state["shoe"]["seen"] = ["5C", "6D", "4H", "3S", "2C"] * 12
        html = bj.render(state)
        self.assertNotIn("true count", html.lower())
        self.assertNotIn("running", html.lower())
        # What it does show is the cards, which is what counting is.
        self.assertIn("out of it:", html)


class Markup(Sandbox):
    def rendered(self, state) -> str:
        return bj.render(state)

    def test_every_image_the_renderer_names_exists(self):
        states = [
            table(),
            table(up="AS", phase="insurance"),
            table(cards=("8S", "3H"), hands=[spot(["8S", "3H"]), spot(["8D", "2C"])]),
            bj.blank_state(),
            settled(),
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
        rows = self.felt_rows(self.rendered(state))
        widths = {row.count("<img") for row in rows}
        self.assertEqual(len(widths), 1, "a staggered row means a staggered table")
        self.assertEqual(len(rows), 3)

    def felt_rows(self, html: str) -> list[str]:
        return re.search(r"<pre>(.*?)</pre>", html, re.DOTALL).group(1).split("\n")

    def test_the_table_is_one_pre(self):
        # GitHub gives a pre a background of its own, so a pre per row bands the
        # table in grey and the felt stops reading as one surface.
        state = table(cards=("8S", "3H"), hands=[spot(["8S", "3H"]), spot(["8D", "2C"])])
        html = self.rendered(state)
        self.assertEqual(len(self.felt_rows(html)), 3)
        # The buttons are their own strip, below the felt.
        self.assertEqual(html.count("<pre>"), 2)

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

    def test_the_finished_hand_says_who_took_it(self):
        # Two totals in the present tense read like a hand still waiting on a
        # decision. This is the line a visitor sees between hands.
        state = table(up="2H", cards=("8D", "3H"), bet=10)
        with stacked("4C", "2C", "5S", "KD"):
            bj.play(state, "double 7", "someone")
        line = bj.headline(state)
        self.assertIn("Hand 7: the dealer", line)
        self.assertIn("the dealer had 19", line)
        self.assertIn("@someone's double came to 15", line)
        self.assertIn("it cost 20u", line)
        # And the table says what to press next, which is the one moment where
        # the thing to click is not obviously a button.
        self.assertIn("Pick a chip to deal hand 8", line)
        self.assertIn(line, bj.render(state))

    def test_the_dealer_is_named_first_because_the_dealer_is_the_top_row(self):
        state = table(up="KH", cards=("8D", "3H"))
        line = bj.headline(state)
        self.assertLess(line.index("dealer"), line.index("you"))

    def test_the_felt_says_whose_row_is_whose(self):
        # Without this a reader has to find a sentence to work out which row is
        # theirs, which is exactly what happened to the first person who looked.
        html = bj.render(table())
        self.assertIn("label-dealer.svg", html)
        self.assertIn("label-you.svg", html)
        self.assertIn('alt="dealer"', html)
        self.assertIn('alt="you"', html)
        # One hand is not marked as the one in play: there is nothing to tell
        # it apart from, and the frame would only read as an alarm.
        self.assertNotIn("label-you-sel.svg", html)

    def test_the_hand_in_play_is_marked_on_its_own_row(self):
        state = table(cards=("8S", "3H"),
                      hands=[spot(["8S", "3H"]), spot(["8D", "2C"])], active=1)
        rows = re.search(r"<pre>(.*?)</pre>", bj.render(state), re.DOTALL).group(1).split("\n")
        self.assertIn("label-dealer", rows[0])
        self.assertIn("label-you.svg", rows[1])
        self.assertIn("label-you-sel.svg", rows[2])

    def test_the_table_explains_itself_in_one_line(self):
        for state in (table(), bj.blank_state()):
            html = bj.render(state)
            self.assertIn("Beat the dealer without going over 21", html)
            self.assertIn("about 30 seconds", html)
            # The rule set is a footer, not the first thing anybody reads.
            self.assertGreater(html.index("6 decks"), html.index("Beat the dealer"))

    def test_a_hand_that_paid_says_so(self):
        state = table(up="TS", cards=("TH", "TD"))
        with stacked("8C"):
            bj.play(state, "stand 7", "someone")
        self.assertIn("it paid 2u", bj.headline(state))

    def test_a_push_ends_level(self):
        state = table(up="TS", cards=("TH", "TD"))
        with stacked("TC"):
            bj.play(state, "stand 7", "someone")
        self.assertIn("it ended level", bj.headline(state))

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

    def test_the_table_names_the_account_that_played_the_hand(self):
        # "You" names nobody: whoever reads the profile is almost never whoever
        # was sitting at the table.
        state = table(up="2H", cards=("8D", "3H"), bet=10)
        with stacked("2C", "5S", "KD"):
            bj.play(state, "stand 7", "kanywst")
        html = self.rendered(state)
        self.assertIn('href="https://github.com/kanywst"', html)
        self.assertIn(">@kanywst</a>", html)
        self.assertNotIn("<th>You</th>", html)

    def test_a_hand_two_accounts_played_names_them_both(self):
        state = table(up="2H", cards=("8D", "3H"), bet=10)
        bj.touch(state, "dealt-it")
        with stacked("2C", "5S", "KD"):
            bj.play(state, "stand 7", "stood-on-it")
        html = self.rendered(state)
        self.assertIn("@dealt-it", html)
        self.assertIn("@stood-on-it", html)

    def test_a_name_that_is_not_a_login_is_never_printed(self):
        # The name arrives from an issue and lands on the profile as a link.
        state = table(up="2H", cards=("8D", "3H"), bet=10)
        with stacked("2C", "5S", "KD"):
            bj.play(state, "stand 7", '"><img src=x onerror=alert(1)>')
        html = self.rendered(state)
        self.assertNotIn("<img src=x", html)
        self.assertNotIn("onerror", html)
        self.assertEqual(state["recent"][0]["by"], [])

    def test_only_a_login_shaped_name_is_a_login(self):
        for name in ("kanywst", "a", "a-b", "9", "x" * 39):
            with self.subTest(name):
                self.assertEqual(bj.handle(name), name)
        for name in ("-lead", "trail-", "double--hyphen", "sp ace", "dot.dot",
                     "x" * 40, "a-" * 30 + "b", "", 12, None, ["kanywst"]):
            with self.subTest(name):
                self.assertEqual(bj.handle(name), "")

    def test_the_settled_hand_is_told_with_the_name_that_played_it(self):
        state = settled(by=("kanywst",))
        line = bj.headline(state)
        self.assertIn("@kanywst had 15", line)
        self.assertNotIn("you had", line)

    def test_two_accounts_on_one_settled_hand_are_both_told(self):
        line = bj.headline(settled(by=("first", "second")))
        self.assertIn("@first and @second had 15", line)

    def test_a_hand_played_before_the_table_kept_names_keeps_the_pronoun(self):
        # The entries written by earlier versions have no name on them, and a
        # sentence with a hole in it is worse than a pronoun.
        line = bj.headline(settled(by=()))
        self.assertIn("you had 15", line)

    def test_the_felt_between_hands_does_not_call_the_reader_the_player(self):
        # The hand still on the felt belongs to whoever played it, and the
        # sentence under it says who. "You" there addresses the wrong person.
        html = bj.render(settled(by=("kanywst",)))
        self.assertIn("label-player.svg", html)
        self.assertIn('alt="player"', html)
        self.assertNotIn("label-you", html)
        self.assertIn("label-dealer.svg", html)

    def test_the_names_on_one_hand_stop_at_what_the_column_holds(self):
        state = table(up="2H", cards=("8D", "3H"), bet=10)
        for i in range(5):
            bj.touch(state, f"player-{i}")
        with stacked("2C", "5S", "KD"):
            bj.play(state, "stand 7", "player-5")
        html = self.rendered(state)
        self.assertIn("@player-0", html)
        self.assertIn("@player-1", html)
        self.assertNotIn("@player-2", html)
        self.assertIn("+4", html)

    def test_one_long_login_takes_the_whole_row_to_itself(self):
        # A login can be 39 characters. Two of them side by side would double
        # the width of the table on a page that is mostly not this table.
        long_names = ["a" * 39, "b" * 39]
        state = table(up="2H", cards=("8D", "3H"), bet=10, by=long_names[:1])
        with stacked("2C", "5S", "KD"):
            bj.play(state, "stand 7", long_names[1])
        row = "\n".join(bj.recent_table(state))
        self.assertNotIn(long_names[1], row)
        self.assertIn("+1", row)
        # The name is cut to what the column can hold, and the link still goes
        # to the account it was cut from.
        self.assertIn(f'href="https://github.com/{long_names[0]}"', row)
        self.assertIn(f'title="@{long_names[0]}"', row)
        self.assertIn("…</a>", row)
        self.assertNotIn(f">@{long_names[0]}<", row)
        # And the sentence under the felt counts the second one too.
        self.assertIn("and 1 other had 11", bj.headline(state))


if __name__ == "__main__":
    unittest.main()
