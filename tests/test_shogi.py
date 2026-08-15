#!/usr/bin/env python3
"""
Tests for the shogi board.

Nobody plays a move here on purpose: the board is played by strangers clicking
links, and the first sign of a broken renderer is a broken image on the profile
or an Action that fails on someone else's turn. These cover the rules, the
markup invariants the board depends on to look like a board, and that every
image the renderer can name exists.

record_win appends to the game log and write_readme rewrites README.md, so both
paths are pointed at a temporary directory before anything runs.
"""

import pathlib
import random
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import shogi  # noqa: E402

KOMA = ROOT / ".github" / "koma"


def sq(square: str) -> tuple[int, int]:
    return shogi.from_sq(square)


def empty_board() -> list[list[str]]:
    return [["" for _ in range(shogi.N)] for _ in range(shogi.N)]


def position(**pieces: str) -> dict:
    """position(**{"5a": "gK"}) -> a state with only those pieces on the board."""
    state = shogi.blank_state()
    state["board"] = empty_board()
    for square, cell in pieces.items():
        row, col = sq(square)
        state["board"][row][col] = cell
    return state


class Sandbox(unittest.TestCase):
    """Keep the repo's own README and game log out of every test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self.tmp.name)
        readme = tmp / "README.md"
        readme.write_text(
            f"# t\n\n{shogi.START_MARKER}\nWAS-HERE\n{shogi.END_MARKER}\n", encoding="utf-8"
        )
        self._paths = (shogi.README_PATH, shogi.LOG_PATH, shogi.STATE_PATH)
        shogi.README_PATH = readme
        shogi.LOG_PATH = tmp / "shogi-log.txt"
        shogi.STATE_PATH = tmp / "shogi.json"
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        shogi.README_PATH, shogi.LOG_PATH, shogi.STATE_PATH = self._paths


class Rules(Sandbox):
    def test_opening_has_thirty_legal_moves(self):
        state = shogi.blank_state()
        moves = sum(
            len(shogi.legal_moves_from(state, (r, c)))
            for r in range(shogi.N)
            for c in range(shogi.N)
            if state["board"][r][c] and shogi.side_of(state["board"][r][c]) == shogi.SENTE
        )
        self.assertEqual(moves, 30)

    def test_two_pawns_on_one_file(self):
        state = position(**{"7g": "sP", "5i": "sK", "5a": "gK"})
        state["hands"][shogi.SENTE] = {"P": 1}
        files = {col for _, col in shogi.legal_drops(state, "P")}
        self.assertNotIn(sq("7e")[1], files)
        self.assertIn(sq("6e")[1], files)

    def test_a_pawn_is_never_dropped_where_it_could_not_move(self):
        state = position(**{"5i": "sK", "5a": "gK"})
        state["hands"][shogi.SENTE] = {"P": 1, "N": 1}
        last = {row for row, _ in shogi.legal_drops(state, "P")}
        self.assertNotIn(0, last)
        knight = {row for row, _ in shogi.legal_drops(state, "N")}
        self.assertNotIn(0, knight)
        self.assertNotIn(1, knight)

    def test_a_move_may_not_leave_the_king_in_check(self):
        # The gold is the only thing between the rook and the king, so of its
        # six moves only the two along the file are left.
        state = position(**{"5i": "sK", "5f": "sG", "5a": "gR", "1a": "gK"})
        moves = sorted(shogi.to_sq(*m) for m in shogi.legal_moves_from(state, sq("5f")))
        self.assertEqual(moves, ["5e", "5g"])

    def test_a_pawn_on_the_last_rank_has_to_promote(self):
        self.assertTrue(shogi.must_promote("P", 0, shogi.SENTE))
        self.assertFalse(shogi.must_promote("P", 1, shogi.SENTE))
        self.assertTrue(shogi.must_promote("N", 1, shogi.SENTE))
        self.assertTrue(shogi.must_promote("P", 8, shogi.GOTE))

    def test_promotion_is_offered_on_entering_the_zone(self):
        state = position(**{"5d": "sP", "5i": "sK", "5a": "gK"})
        state["selected"] = "5d"
        self.assertEqual(shogi.play(state, "mv 5d5c", "kt"), "Promote or not?")
        self.assertEqual(state["pending"], {"from": "5d", "to": "5c"})
        shogi.play(state, "pro yes", "kt")
        self.assertEqual(state["board"][sq("5c")[0]][sq("5c")[1]], "s+P")
        self.assertEqual(state["last"], "P-5c+")

    def test_checkmate_ends_the_game(self):
        # 頭金: a gold in front of the king covers every square it could run to,
        # and the rook coming to 5c defends the gold. The rook enters the
        # promotion zone on the way, so the offer has to be answered first.
        state = position(**{"5a": "gK", "5b": "sG", "5i": "sR", "9i": "sK"})
        state["turn"] = shogi.SENTE
        state["selected"] = "5i"
        self.assertEqual(shogi.play(state, "mv 5i5c", "kt"), "Promote or not?")
        shogi.play(state, "pro no", "kt")
        self.assertEqual(state["status"], "over")
        self.assertEqual(state["winner"], shogi.SENTE)
        self.assertEqual(state["reason"], "Checkmate")

    def test_resign_needs_a_move_first(self):
        state = shogi.blank_state()
        self.assertIn("Play a move first", shogi.play(state, "resign", "stranger"))
        self.assertEqual(state["status"], "playing")
        state["players"] = ["stranger"]
        shogi.play(state, "resign", "stranger")
        self.assertEqual(state["winner"], shogi.GOTE)
        self.assertEqual(state["record"][shogi.GOTE], 1)

    def test_a_stale_link_is_not_applied_to_the_current_selection(self):
        state = shogi.blank_state()
        state["selected"] = "7g"
        self.assertIn("board moved on", shogi.play(state, "mv 2g2f", "kt"))
        self.assertEqual(state["board"][sq("2g")[0]][sq("2g")[1]], "sP")

    def test_parse_takes_the_documented_commands_and_nothing_else(self):
        for title in ("shogi|sel 7g", "shogi|sel *P", "shogi|mv 7g7f",
                      "shogi|pro yes", "shogi|cancel", "shogi|resign", "shogi|new"):
            self.assertIsNotNone(shogi.parse(title), title)
        for title in ("shogi|drop table", "shogi|sel 0z", "shogi|mv 7g", "hello"):
            self.assertIsNone(shogi.parse(title), title)


class Markup(Sandbox):
    """The board only looks like a board while these hold."""

    def board(self, state: dict) -> str:
        return shogi.render_board(state)

    def test_one_rank_per_line_and_nine_squares_on_each(self):
        body = self.board(shogi.blank_state())
        self.assertTrue(body.startswith('<div align="center"><pre>'))
        self.assertTrue(body.endswith("</pre></div>"))
        inner = body[len('<div align="center"><pre>'):-len("</pre></div>")]
        ranks = inner.split("\n")
        self.assertEqual(len(ranks), shogi.N)
        for rank in ranks:
            self.assertEqual(rank.count("<a href="), shogi.N)
            self.assertEqual(rank.count("<img "), shogi.N)
            self.assertEqual(rank.strip(), rank)

    def test_no_size_attributes_and_every_image_aligned_top(self):
        # A sized image gets a border radius and a background from GitHub, and
        # without align=top the ranks are pushed apart by a baseline.
        body = self.board(shogi.blank_state())
        self.assertNotIn("width=", body)
        self.assertNotIn("height=", body)
        self.assertEqual(body.count("<img "), body.count('align="top"'))

    def test_nothing_can_end_the_raw_html_block(self):
        for state in self.states():
            self.assertNotIn("\n\n", self.board(state))

    def test_only_the_side_to_move_keeps_its_colour(self):
        state = shogi.blank_state()
        body = self.board(state)
        self.assertEqual(body.count("-idle.svg"), 20)
        self.assertEqual(len(re.findall(r' to move"', body)), 20)

        state["status"], state["winner"] = "over", shogi.SENTE
        finished = self.board(state)
        self.assertNotIn("-idle.svg", finished)
        self.assertNotIn(" to move", finished)

    def test_a_finished_game_with_no_winner_still_renders(self):
        # load_state accepts the status while rejecting a bad winner or reason.
        state = shogi.blank_state()
        state["status"] = "over"
        out = shogi.render(state)
        self.assertIn("Checkmate.", out)
        self.assertNotIn("None", out)

    def test_a_hand_is_drawn_as_its_pieces(self):
        state = shogi.blank_state()
        state["hands"][shogi.SENTE] = {"P": 2}
        out = shogi.render(state)
        self.assertIn("black pawn in hand to move", out)
        self.assertIn("×2", out)
        self.assertNotIn("in hand:", out.lower())

    def test_a_selection_is_framed_wherever_it_was_made(self):
        # Not just that the art exists, but that the right art is picked: a
        # piece picked up from hand has to show it the way one on the board does.
        state = shogi.blank_state()
        state["selected"] = "7g"
        board = self.board(state)
        self.assertEqual(board.count("sP-sel.svg"), 1)
        self.assertIn("7g black pawn selected", board)

        state = shogi.blank_state()
        state["hands"][shogi.SENTE] = {"P": 1, "S": 1}
        state["selected"] = "*P"
        hand = shogi.render_hand(state, shogi.SENTE)
        self.assertIn("sP-sel.svg", hand)
        self.assertIn("black pawn in hand selected", hand)
        self.assertNotIn("sS-sel.svg", hand)

    def test_every_image_the_renderer_names_exists(self):
        named = set()
        for state in self.states():
            named |= set(re.findall(r"koma/([\w-]+)\.svg", shogi.render(state)))
        self.assertTrue(named)
        missing = sorted(n for n in named if not (KOMA / f"{n}.svg").exists())
        self.assertEqual(missing, [])

    def test_write_readme_only_touches_its_own_block(self):
        shogi.write_readme(shogi.blank_state())
        content = shogi.README_PATH.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("# t\n"))
        self.assertEqual(content.count(shogi.START_MARKER), 1)
        self.assertEqual(content.count(shogi.END_MARKER), 1)
        self.assertNotIn("WAS-HERE", content)

    def states(self):
        """One state per branch the renderer has."""
        base = shogi.blank_state()
        yield base
        for turn in (shogi.SENTE, shogi.GOTE):
            selected = shogi.blank_state()
            selected["turn"] = turn
            selected["selected"] = "7g" if turn == shogi.SENTE else "3c"
            yield selected

            dropping = shogi.blank_state()
            dropping["turn"] = turn
            dropping["hands"][turn] = {"P": 1, "R": 2}
            dropping["selected"] = "*P"
            yield dropping

            pending = shogi.blank_state()
            pending["turn"] = turn
            pending["pending"] = {"from": "7g", "to": "7f"}
            yield pending

            over = shogi.blank_state()
            over["status"] = "over"
            over["winner"] = turn
            over["reason"] = "Resignation"
            over["last"] = "resigns"
            yield over

        promoted = shogi.blank_state()
        for col, kind in enumerate(["+P", "+L", "+N", "+S", "+B", "+R", "K", "G", "P"]):
            promoted["board"][4][col] = shogi.SENTE + kind
            promoted["board"][3][col] = shogi.GOTE + kind
        yield promoted


class Playouts(Sandbox):
    """Random games, because the real board is driven by strangers."""

    def test_games_run_to_the_end_without_falling_over(self):
        rng = random.Random(20260815)
        for game in range(8):
            state = shogi.blank_state()
            for _ in range(240):
                if state["status"] != "playing":
                    break
                side = state["turn"]
                moves = [
                    (f"{shogi.to_sq(r, c)}", shogi.to_sq(*to))
                    for r in range(shogi.N)
                    for c in range(shogi.N)
                    if state["board"][r][c] and shogi.side_of(state["board"][r][c]) == side
                    for to in shogi.legal_moves_from(state, (r, c))
                ]
                self.assertTrue(moves, f"game {game}: no move but the game is on")
                frm, to = rng.choice(moves)
                state["selected"] = frm
                shogi.play(state, f"mv {frm}{to}", "kt")
                if state["pending"]:
                    shogi.play(state, f"pro {rng.choice(['yes', 'no'])}", "kt")
                self.assertIsNone(state["selected"])
                for row in state["board"]:
                    self.assertEqual(len(row), shogi.N)
                shogi.write_readme(state)


if __name__ == "__main__":
    unittest.main()
