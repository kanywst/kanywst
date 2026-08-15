#!/usr/bin/env python3
"""
shogi.py

Called from GitHub Actions. Reads an issue title as one move, plays it, and
redraws the SHOGI block in README.md.

Same machinery as the guest book: open an issue -> Action -> rewrite between
the markers.

A move takes two clicks. Click a piece on the board or in hand to select it,
then click a square it can reach. Linking every legal move at once would mean
hundreds of links, so the destinations only appear once something is selected.
The same handling as marcizhu's chess board.

Issue titles:
  shogi|sel 7g      - select a piece on the board
  shogi|sel *P      - select a piece in hand
  shogi|mv 7g7f     - move or drop the selected piece
  shogi|pro yes|no  - answer the promotion question
  shogi|cancel      - drop the selection
  shogi|resign      - resign, so a game that never reaches mate can still end
  shogi|new         - start the next game once one is decided

The running record lives across games in .github/shogi.json. A finished game is
not cleared automatically; the result stays up until someone starts a new one.

Environment:
  ISSUE_TITLE / ISSUE_USER / ISSUE_NUMBER

Standard output becomes the comment on the issue.
"""

import json
import os
import pathlib
import re
import sys
from datetime import datetime, timezone

README_PATH = pathlib.Path("README.md")
STATE_PATH = pathlib.Path(".github/shogi.json")
LOG_PATH = pathlib.Path(".github/shogi-log.txt")

START_MARKER = "<!-- SHOGI:START -->"
END_MARKER = "<!-- SHOGI:END -->"

N = 9
SENTE = "s"
GOTE = "g"

REPO = "kanywst/kanywst"
ASSET = f"https://raw.githubusercontent.com/{REPO}/main/.github/koma"
BODY = "Just+click+Submit+new+issue.+The+board+updates+in+about+30+seconds."

SIDE_NAME = {SENTE: "Black", GOTE: "White"}
LETTER = {"P": "P", "L": "L", "N": "N", "S": "S", "G": "G", "B": "B", "R": "R", "K": "K",
          "+P": "+P", "+L": "+L", "+N": "+N", "+S": "+S", "+B": "+B", "+R": "+R"}
WORD = {"P": "pawn", "L": "lance", "N": "knight", "S": "silver",
        "G": "gold", "B": "bishop", "R": "rook"}
HAND_ORDER = ["R", "B", "G", "S", "N", "L", "P"]
KANJI = {
    "P": "歩", "L": "香", "N": "桂", "S": "銀",
    "G": "金", "B": "角", "R": "飛", "K": "王",
    "+P": "と", "+L": "杏", "+N": "圭", "+S": "全", "+B": "馬", "+R": "龍",
}

RANKS = "abcdefghi"

MAX_PLAYERS = 200      # Only the count is shown; keeping everyone just grows the state.
MAX_LOG_GAMES = 100    # The oldest games fall off first.

GOLD = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, 0)]

# Per piece: (directions it steps one square, directions it slides any distance).
# Written for Black, whose forward is the direction the row number decreases.
STEPS = {
    "P": [(-1, 0)],
    "N": [(-2, -1), (-2, 1)],
    "S": [(-1, -1), (-1, 0), (-1, 1), (1, -1), (1, 1)],
    "G": GOLD,
    "K": [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)],
    "+P": GOLD, "+L": GOLD, "+N": GOLD, "+S": GOLD,
    "+B": [(-1, 0), (1, 0), (0, -1), (0, 1)],
    "+R": [(-1, -1), (-1, 1), (1, -1), (1, 1)],
}
SLIDES = {
    "L": [(-1, 0)],
    "B": [(-1, -1), (-1, 1), (1, -1), (1, 1)],
    "R": [(-1, 0), (1, 0), (0, -1), (0, 1)],
    "+B": [(-1, -1), (-1, 1), (1, -1), (1, 1)],
    "+R": [(-1, 0), (1, 0), (0, -1), (0, 1)],
}

INITIAL_BACK = ["L", "N", "S", "G", "K", "G", "S", "N", "L"]


# --------------------------------------------------------------------------
# Coordinates. Files count 1..9 from the right, so the leftmost file on screen
# (file 9) is column 0. Ranks run a..i from the top, so row 0 is rank a.
# --------------------------------------------------------------------------

def to_sq(row: int, col: int) -> str:
    return f"{N - col}{RANKS[row]}"


def from_sq(sq: str) -> tuple[int, int]:
    return RANKS.index(sq[1]), N - int(sq[0])


def on_board(row: int, col: int) -> bool:
    return 0 <= row < N and 0 <= col < N


def side_of(cell: str) -> str:
    return cell[0]


def kind_of(cell: str) -> str:
    """'s+R' -> '+R'"""
    return cell[1:]


def base_of(cell: str) -> str:
    """'s+R' -> 'R'"""
    return kind_of(cell).lstrip("+")


def forward(side: str) -> int:
    return -1 if side == SENTE else 1


# --------------------------------------------------------------------------
# Position
# --------------------------------------------------------------------------

def initial_board() -> list[list[str]]:
    board = [["" for _ in range(N)] for _ in range(N)]
    for col, piece in enumerate(INITIAL_BACK):
        board[0][col] = GOTE + piece
        board[8][col] = SENTE + piece
    board[1][1] = GOTE + "R"
    board[1][7] = GOTE + "B"
    board[7][1] = SENTE + "B"
    board[7][7] = SENTE + "R"
    for col in range(N):
        board[2][col] = GOTE + "P"
        board[6][col] = SENTE + "P"
    return board


def blank_state() -> dict:
    return {
        "board": initial_board(),
        "hands": {SENTE: {}, GOTE: {}},
        "turn": SENTE,
        "selected": None,
        "pending": None,
        "status": "playing",
        "winner": None,
        "reason": None,
        "last": None,
        "moves": [],
        "games": 0,
        "record": {SENTE: 0, GOTE: 0},
        "players": [],
    }


def load_state() -> dict:
    """Fill whatever cannot be read with defaults, so a broken state file does not
    stop the board for good."""
    if not STATE_PATH.exists():
        return blank_state()
    fresh = blank_state()
    try:
        stored = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fresh
    if not isinstance(stored, dict):
        return fresh

    board = stored.get("board")
    if (not isinstance(board, list) or len(board) != N
            or any(not isinstance(r, list) or len(r) != N for r in board)):
        return fresh

    # Check the cells too. The right shape with wrong contents crashes the render.
    known = set(KANJI) | {""}
    for row in board:
        for cell in row:
            if not isinstance(cell, str):
                return fresh
            if cell and (cell[0] not in (SENTE, GOTE) or cell[1:] not in known):
                return fresh

    def hands_ok(value) -> bool:
        return (isinstance(value, dict) and set(value) == {SENTE, GOTE}
                and all(isinstance(h, dict)
                        and all(k in KANJI and isinstance(n, int) and n >= 0
                                for k, n in h.items())
                        for h in value.values()))

    # Take only what type checks. A key that does not is left at its default.
    checks = {
        "board": lambda v: True,
        "hands": hands_ok,
        "turn": lambda v: v in (SENTE, GOTE),
        "selected": lambda v: v is None or (isinstance(v, str) and len(v) == 2),
        "pending": lambda v: v is None or (isinstance(v, dict) and {"from", "to"} <= set(v)),
        "status": lambda v: v in ("playing", "over"),
        "winner": lambda v: v is None or v in (SENTE, GOTE),
        "reason": lambda v: v is None or isinstance(v, str),
        "last": lambda v: v is None or isinstance(v, str),
        "moves": lambda v: isinstance(v, list) and all(isinstance(m, str) for m in v),
        "games": lambda v: isinstance(v, int) and v >= 0,
        "record": lambda v: (isinstance(v, dict)
                             and all(isinstance(n, int) and n >= 0 for n in v.values())),
        "players": lambda v: isinstance(v, list) and all(isinstance(u, str) for u in v),
    }
    for key, ok in checks.items():
        if key in stored:
            try:
                if ok(stored[key]):
                    fresh[key] = stored[key]
            except (TypeError, AttributeError):
                pass
    return fresh


# --------------------------------------------------------------------------
# Reach
# --------------------------------------------------------------------------

def destinations(board: list[list[str]], row: int, col: int) -> list[tuple[int, int]]:
    """Squares the piece can reach. Own pieces are excluded, but a move that leaves
    the king in check is not."""
    cell = board[row][col]
    side = side_of(cell)
    kind = kind_of(cell)
    out = []

    # The tables are written for Black, so White's forward is flipped.
    def step_row(drow: int) -> int:
        return drow if side == SENTE else -drow

    for drow, dcol in STEPS.get(kind, []):
        r, c = row + step_row(drow), col + dcol
        if on_board(r, c) and (not board[r][c] or side_of(board[r][c]) != side):
            out.append((r, c))

    for drow, dcol in SLIDES.get(kind, []):
        step_r = step_row(drow)
        r, c = row + step_r, col + dcol
        while on_board(r, c):
            if not board[r][c]:
                out.append((r, c))
            else:
                if side_of(board[r][c]) != side:
                    out.append((r, c))
                break
            r += step_r
            c += dcol

    return out


def king_square(board: list[list[str]], side: str) -> tuple[int, int] | None:
    for r in range(N):
        for c in range(N):
            if board[r][c] == side + "K":
                return r, c
    return None


def in_check(board: list[list[str]], side: str) -> bool:
    king = king_square(board, side)
    if king is None:
        return True
    for r in range(N):
        for c in range(N):
            cell = board[r][c]
            if cell and side_of(cell) != side and king in destinations(board, r, c):
                return True
    return False


def promotion_zone(row: int, side: str) -> bool:
    return row <= 2 if side == SENTE else row >= 6


def must_promote(kind: str, row: int, side: str) -> bool:
    """A piece that would have nowhere left to go has to promote."""
    last = 0 if side == SENTE else N - 1
    second = 1 if side == SENTE else N - 2
    if kind in ("P", "L"):
        return row == last
    if kind == "N":
        return row in (last, second)
    return False


def can_promote(kind: str, from_row: int, to_row: int, side: str) -> bool:
    if kind.startswith("+") or kind in ("G", "K"):
        return False
    return promotion_zone(from_row, side) or promotion_zone(to_row, side)


def apply_move(board, hands, frm, to, promote) -> None:
    fr, fc = frm
    tr, tc = to
    cell = board[fr][fc]
    side = side_of(cell)
    captured = board[tr][tc]
    if captured:
        hands[side][base_of(captured)] = hands[side].get(base_of(captured), 0) + 1
    board[fr][fc] = ""
    board[tr][tc] = side + ("+" + base_of(cell) if promote else kind_of(cell))


def legal_moves_from(state: dict, frm: tuple[int, int]) -> list[tuple[int, int]]:
    """Destinations, minus the ones that leave the king in check."""
    board = state["board"]
    side = side_of(board[frm[0]][frm[1]])
    kind = kind_of(board[frm[0]][frm[1]])
    out = []
    for to in destinations(board, *frm):
        # Where staying unpromoted leaves it stuck, test the move as a promotion
        promote = must_promote(kind, to[0], side)
        trial = [row[:] for row in board]
        trial_hands = {s: dict(h) for s, h in state["hands"].items()}
        apply_move(trial, trial_hands, frm, to, promote)
        if not in_check(trial, side):
            out.append(to)
    return out


def legal_drops(state: dict, piece: str, check_pawn_mate: bool = True) -> list[tuple[int, int]]:
    board = state["board"]
    side = state["turn"]
    out = []

    # Two pawns on one file. A file already holding an unpromoted pawn is closed.
    blocked_files = set()
    if piece == "P":
        for c in range(N):
            for r in range(N):
                if board[r][c] == side + "P":
                    blocked_files.add(c)
                    break

    for r in range(N):
        for c in range(N):
            if board[r][c]:
                continue
            if must_promote(piece, r, side):
                continue
            if piece == "P" and c in blocked_files:
                continue

            trial = [row[:] for row in board]
            trial[r][c] = side + piece
            if in_check(trial, side):
                continue
            # Mate by dropping a pawn. This asks whether the opponent has a way
            # out, and looking for another pawn drop mate inside that answer
            # never terminates, so the search stops one level down.
            if piece == "P" and check_pawn_mate:
                other = GOTE if side == SENTE else SENTE
                trial_state = {"board": trial, "hands": state["hands"], "turn": other}
                if in_check(trial, other) and not has_any_legal_move(
                    trial_state, other, check_pawn_mate=False
                ):
                    continue
            out.append((r, c))
    return out


def has_any_legal_move(state: dict, side: str, check_pawn_mate: bool = True) -> bool:
    board = state["board"]
    for r in range(N):
        for c in range(N):
            if board[r][c] and side_of(board[r][c]) == side:
                if legal_moves_from({"board": board, "hands": state["hands"]}, (r, c)):
                    return True
    probe = {"board": board, "hands": state["hands"], "turn": side}
    for piece, count in state["hands"].get(side, {}).items():
        if count > 0 and legal_drops(probe, piece, check_pawn_mate):
            return True
    return False


def is_checkmate(state: dict, side: str) -> bool:
    return in_check(state["board"], side) and not has_any_legal_move(state, side)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def issue_url(command: str) -> str:
    quoted = command.replace("|", "%7C").replace(" ", "+").replace("*", "%2A")
    return f"https://github.com/{REPO}/issues/new?title=shogi%7C{quoted}&body={BODY}"


def img(name: str, alt: str) -> str:
    # No width or height: GitHub gives any sized image a 6px border radius and a
    # background of its own, which turns a board into a grid of rounded tiles.
    # align=top is what closes the gap a baseline would otherwise leave between
    # ranks. Written as img because markdown's ![]() does not expand in raw HTML.
    return f'<img src="{ASSET}/{name}.svg" align="top" alt="{alt}">'


def koma_img(cell: str, square: str, selected: bool = False) -> str:
    kind = kind_of(cell)
    name = side_of(cell) + kind.replace("+", "p") + ("-sel" if selected else "")
    # Nothing but orientation says whose piece it is, so the alt text says it
    side = SIDE_NAME[side_of(cell)].lower()
    word = WORD.get(kind.lstrip("+"), "king")
    return img(name, f"{square} {side} {word}{' selected' if selected else ''}")


def plate_img(state: dict, side: str) -> str:
    """The name plate for one side, inked when it is that side's move."""
    if state["status"] != "playing":
        suffix = "-win" if state["winner"] == side else ""
    else:
        suffix = "-turn" if state["turn"] == side else ""
    mark = "Black" if side == SENTE else "White"
    note = {"-turn": " to move", "-win": " wins", "": ""}[suffix]
    return f'<img src="{ASSET}/plate-{side}{suffix}.svg" align="top" alt="{mark}{note}">'


def render_board(state: dict) -> str:
    board = state["board"]
    selected = state["selected"]
    turn = state["turn"]
    over = state["status"] != "playing"

    targets: set[tuple[int, int]] = set()
    if selected and not over and not state["pending"]:
        if selected.startswith("*"):
            targets = set(legal_drops(state, selected[1:]))
        else:
            targets = set(legal_moves_from(state, from_sq(selected)))

    rows = []
    for r in range(N):
        cells = []
        for c in range(N):
            cell = board[r][c]
            sq = to_sq(r, c)
            target = (r, c) in targets
            if cell:
                inner = koma_img(cell, sq, selected=(sq == selected))
            else:
                inner = img("target" if target else "empty",
                            f"{sq} legal move" if target else "")

            if target:
                href = issue_url(f"mv {selected}{sq}")
            elif not over and not state["pending"] and cell and side_of(cell) == turn:
                href = issue_url(f"sel {sq}")
            else:
                # Without a link of our own, GitHub wraps the image in one to the
                # raw SVG, and a visitor clicking an empty square opens a .svg.
                href = f"https://github.com/{REPO}#shogi"
            cells.append(f'<a href="{href}">{inner}</a>')
        rows.append("".join(cells))

    # A table cannot be the board: GitHub pads and borders every cell, and the
    # squares read as a spreadsheet. Ranks are one long line each instead, broken
    # with <br>. The newline after each break is collapsed away by the browser,
    # so the ranks meet with no seam.
    return '<p align="center">\n' + "<br>\n".join(rows) + "\n</p>"


def render_hand(state: dict, side: str) -> str:
    hand = state["hands"].get(side, {})
    held = [(p, n) for p in HAND_ORDER for n in [hand.get(p, 0)] if n > 0]
    # An empty hand is worth no line at all. The plate below it names the side.
    if not held:
        return ""

    selectable = (
        side == state["turn"]
        and state["status"] == "playing"
        and not state["pending"]
    )
    parts = []
    for piece, count in held:
        label = KANJI[piece] + (f"×{count}" if count > 1 else "")
        if selectable:
            parts.append(f'<a href="{issue_url(f"sel *{piece}")}">{label}</a>')
        else:
            parts.append(label)
    return "In hand: " + " ".join(parts)


def render(state: dict) -> str:
    turn = state["turn"]
    status = state["status"]
    lines = []

    # Only what the plates do not already say. Naming the side to move is their
    # job, and repeating it above the board is what made this hard to read.
    if status != "playing":
        headline = f"{state.get('reason', 'Checkmate')}."
    elif state["pending"]:
        # The piece has not moved yet, so name both squares. "Promote?" alone
        # does not say what is being promoted.
        headline = (f"{state['pending']['from']} to {state['pending']['to']}."
                    " Promote the piece in the red frame?")
    elif state["selected"]:
        if state["selected"].startswith("*"):
            headline = (f"Dropping a {WORD[state['selected'][1:]]}."
                        " Click a red circle to place it.")
        else:
            headline = (f"The piece in the red frame on {state['selected']} is selected."
                        " Click a red circle to move it there.")
    else:
        headline = "Check." if in_check(state["board"], turn) else ""

    if headline:
        lines.append(f'<p align="center">{headline}</p>')
        lines.append("")

    # White plays from the top of the board and Black from the bottom, so each
    # plate sits on the side of the board it belongs to.
    def centred(html: str) -> None:
        lines.append(f'<p align="center">{html}</p>')
        lines.append("")

    centred(plate_img(state, GOTE))
    if render_hand(state, GOTE):
        centred(render_hand(state, GOTE))
    lines.append(render_board(state))
    lines.append("")
    if render_hand(state, SENTE):
        centred(render_hand(state, SENTE))
    centred(plate_img(state, SENTE))

    if status != "playing":
        call = f'<a href="{issue_url("new")}">Start a new game</a>'
    elif state["pending"]:
        yes = issue_url("pro yes")
        no = issue_url("pro no")
        call = f'<a href="{yes}">Yes</a> · <a href="{no}">No</a>'
    elif state["selected"]:
        # The headline above the board is easy to scroll past, so the circles
        # are explained under the board as well.
        if state["selected"].startswith("*"):
            where = f"you can drop the {WORD[state['selected'][1:]]}"
        else:
            where = f"the piece on {state['selected']} can go"
        call = (f"Red circles are where {where}"
                f' · <a href="{issue_url("cancel")}">Pick something else</a>')
    else:
        # Resignation, so a game that never reaches mate cannot stall the board
        call = (
            "Click a piece, then a square. Takes about 30 seconds."
            f' · <a href="{issue_url("resign")}">Resign</a>'
        )

    lines.append(f'<p align="center">{call}</p>')
    lines.append("")

    # The tally is kept across games. Cleared after each one, it records nothing.
    record = state.get("record", {SENTE: 0, GOTE: 0})
    games = state.get("games", 0)
    played = len(state.get("players", []))
    footer = [f"Last move: {state['last']}"] if state["last"] else []
    footer.append(f"Black {record.get(SENTE, 0)} · White {record.get(GOTE, 0)}")
    footer.append(f"{games} game{'' if games == 1 else 's'}")
    footer.append(f"{played} player{'' if played == 1 else 's'}")
    lines.append(f'<p align="center">{" · ".join(footer)}</p>')
    return "\n".join(lines)


def write_readme(state: dict) -> None:
    content = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )
    if not pattern.search(content):
        raise SystemExit("SHOGI markers not found in README.md")
    block = f"{START_MARKER}\n{render(state)}\n{END_MARKER}"
    README_PATH.write_text(pattern.sub(lambda _: block, content), encoding="utf-8")


# --------------------------------------------------------------------------
# Playing a move
# --------------------------------------------------------------------------

def describe(kind: str, to, promote: bool, dropped: bool, captured: bool) -> str:
    """P-7f, Bx2b+, G*5b."""
    join = "*" if dropped else ("x" if captured else "-")
    return f"{LETTER[kind]}{join}{to_sq(*to)}{'+' if promote else ''}"


def record_move(state: dict, notation: str) -> str:
    state.setdefault("moves", []).append(notation)
    return notation


def append_log(state: dict) -> None:
    """Append a finished game to the log kept in the repo."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    number = state.get("games", 0)
    moves = state.get("moves", [])
    played = [m for m in moves if m != "resigns"]
    header = (
        f"{stamp}  game {number}  "
        f"{SIDE_NAME[state['winner']]} wins by {state['reason'].lower()}  "
        f"{len(played)} move{'' if len(played) == 1 else 's'}"
    )
    body = "\n".join(
        "  " + " ".join(moves[i:i + 12]) for i in range(0, len(moves), 12)
    )
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = header + "\n" + (body + "\n" if body else "") + "\n"
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else ""
    head, _, rest = existing.partition("\n\n")
    games = [g for g in rest.split("\n\n") if g.strip()]
    games.append(entry.strip())
    games = games[-MAX_LOG_GAMES:]
    LOG_PATH.write_text(head + "\n\n" + "\n\n".join(games) + "\n\n", encoding="utf-8")


def record_win(state: dict, winner: str, reason: str) -> None:
    state["status"] = "over"
    state["winner"] = winner
    state["reason"] = reason
    state["games"] = state.get("games", 0) + 1
    record = state.setdefault("record", {SENTE: 0, GOTE: 0})
    record[winner] = record.get(winner, 0) + 1
    append_log(state)


def finish_turn(state: dict, note: str) -> str:
    other = GOTE if state["turn"] == SENTE else SENTE
    state["turn"] = other
    state["selected"] = None
    state["pending"] = None

    # Shogi has no stalemate. A side with no move simply loses.
    if not has_any_legal_move(state, other):
        reason = "Checkmate" if in_check(state["board"], other) else "Stalemate"
        record_win(state, GOTE if other == SENTE else SENTE, reason)
        return f"{note} {reason}. {SIDE_NAME[state['winner']]} wins."
    if in_check(state["board"], other):
        return f"{note} Check."
    return note


def play(state: dict, command: str, user: str) -> str:
    parts = command.split()
    verb = parts[0]

    if verb == "new":
        if state["status"] == "playing":
            return "That game is still going. Take a turn instead."
        keep_players = state.get("players", [])
        keep_games = state.get("games", 0)
        keep_record = state.get("record", {SENTE: 0, GOTE: 0})
        fresh = blank_state()
        fresh["players"] = keep_players
        fresh["games"] = keep_games
        fresh["record"] = keep_record
        state.clear()
        state.update(fresh)
        return "New board. Black starts."

    if state["status"] != "playing":
        return "That game is over. Start a new one."

    if verb == "resign":
        if user not in state.get("players", []):
            return "Play a move first, then you can resign."
        loser = state["turn"]
        winner = GOTE if loser == SENTE else SENTE
        state["last"] = record_move(state, "resigns")
        record_win(state, winner, "Resignation")
        state["selected"] = None
        state["pending"] = None
        return f"{SIDE_NAME[loser]} resigns. {SIDE_NAME[winner]} wins."

    if verb == "cancel":
        state["selected"] = None
        state["pending"] = None
        return "Cleared."

    if verb == "sel":
        if state["pending"]:
            return "Answer the promotion question first."
        target = parts[1]
        if target.startswith("*"):
            piece = target[1:]
            if state["hands"][state["turn"]].get(piece, 0) < 1:
                return f"No {WORD[piece]} in hand."
            if not legal_drops(state, piece):
                return f"Nowhere to drop a {WORD[piece]}."
        else:
            row, col = from_sq(target)
            cell = state["board"][row][col]
            if not cell or side_of(cell) != state["turn"]:
                return f"No {SIDE_NAME[state['turn']]} piece on {target}."
            if not legal_moves_from(state, (row, col)):
                return f"The piece on {target} has no legal move."
        state["selected"] = target
        return "Selected. Now click a square."

    if verb == "mv":
        if state["pending"]:
            return "Answer the promotion question first."
        selected = state["selected"]
        if not selected:
            return "Pick a piece first."
        arg = parts[1]
        # Never apply a link drawn before the board moved to whatever is selected now
        if arg[:-2] != selected:
            return "The board moved on since that link was drawn. Click again."

        if selected.startswith("*"):
            piece = selected[1:]
            to = from_sq(arg[-2:])
            if to not in legal_drops(state, piece):
                return "Cannot drop there."
            state["board"][to[0]][to[1]] = state["turn"] + piece
            state["hands"][state["turn"]][piece] -= 1
            if state["hands"][state["turn"]][piece] == 0:
                del state["hands"][state["turn"]][piece]
            state["last"] = record_move(state, describe(piece, to, False, True, False))
            state["selected"] = None
            return finish_turn(state, f"{state['last']}.")

        frm = from_sq(selected)
        to = from_sq(arg[-2:])
        if to not in legal_moves_from(state, frm):
            return "Cannot move there."

        kind = kind_of(state["board"][frm[0]][frm[1]])
        captured = bool(state["board"][to[0]][to[1]])
        if must_promote(kind, to[0], state["turn"]):
            apply_move(state["board"], state["hands"], frm, to, True)
            state["last"] = record_move(state, describe(kind, to, True, False, captured))
            state["selected"] = None
            return finish_turn(state, f"{state['last']}.")

        if can_promote(kind, frm[0], to[0], state["turn"]):
            state["pending"] = {"from": selected, "to": to_sq(*to)}
            return "Promote or not?"

        apply_move(state["board"], state["hands"], frm, to, False)
        state["last"] = record_move(state, describe(kind, to, False, False, captured))
        state["selected"] = None
        return finish_turn(state, f"{state['last']}.")

    if verb == "pro":
        if not state["pending"]:
            return "Nothing is waiting on a promotion answer."
        promote = parts[1] == "yes"
        frm = from_sq(state["pending"]["from"])
        to = from_sq(state["pending"]["to"])
        kind = kind_of(state["board"][frm[0]][frm[1]])
        captured = bool(state["board"][to[0]][to[1]])
        apply_move(state["board"], state["hands"], frm, to, promote)
        state["last"] = record_move(state, describe(kind, to, promote, False, captured))
        state["pending"] = None
        state["selected"] = None
        return finish_turn(state, f"{state['last']}.")

    return f"Could not read '{command}' as a move."


def parse(title: str) -> str | None:
    match = re.search(
        r"shogi\s*\|\s*("
        r"new|cancel|resign"
        r"|sel\s+(?:\*[PLNSGBR]|[1-9][a-i])"
        r"|mv\s+(?:\*[PLNSGBR][1-9][a-i]|[1-9][a-i][1-9][a-i])"
        r"|pro\s+(?:yes|no)"
        r")",
        title,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1).strip())


def main() -> None:
    title = os.environ.get("ISSUE_TITLE", "")
    user = os.environ.get("ISSUE_USER", "someone")

    command = parse(title)
    if command is None:
        # exit 1 leaves the heredoc open, turns the workflow red and stops the
        # issue being closed. An unreadable move gets nothing but an answer.
        print("That is not a move I can read. Click a piece on the board instead.")
        return

    state = load_state()
    before = json.dumps(state["board"], ensure_ascii=False)
    message = play(state, command, user)

    # Count a player only when the board actually moved, never on a rejected click.
    moved = json.dumps(state["board"], ensure_ascii=False) != before
    if moved and user not in state["players"]:
        state["players"].append(user)
        del state["players"][:-MAX_PLAYERS]

    write_readme(state)
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)
    print(message)


if __name__ == "__main__":
    main()
