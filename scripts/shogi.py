#!/usr/bin/env python3
"""
shogi.py

GitHub Actions から呼び出され、Issue のタイトルを 1 手として将棋の局面に反映し、
README.md の SHOGI マーカー間を描き直す。

ゲストブックと同じ仕組み (Issue を立てる → Action → マーカー間を書き換え)。

指し手は 2 手順のクリックで進む。盤上の駒か持ち駒をクリックして選び、
次に行ける升をクリックする。合法手を全部リンクにすると数百本になるため、
選択してから行き先だけを出す。marcizhu のチェスと同じ操作。

Issue タイトル:
  shogi|sel 7g      - 盤上の駒を選ぶ
  shogi|sel *P      - 持ち駒を選ぶ
  shogi|mv 7g7f     - 選んだ駒を動かす / 打つ
  shogi|pro yes|no  - 成るかどうかを答える
  shogi|cancel      - 選択をやめる
  shogi|resign      - 投了する。詰みまで行かない局面で盤が止まるのを防ぐ
  shogi|new         - 決着後に次の対局を始める

勝敗は対局をまたいで .github/shogi.json に残る。終局しても自動では初期化せず、
だれかが「次の対局を始める」を押すまで結果を出したままにする。

環境変数:
  ISSUE_TITLE / ISSUE_USER / ISSUE_NUMBER

標準出力が Issue へのコメントになる。
"""

import json
import os
import pathlib
import re
import sys

README_PATH = pathlib.Path("README.md")
STATE_PATH = pathlib.Path(".github/shogi.json")

START_MARKER = "<!-- SHOGI:START -->"
END_MARKER = "<!-- SHOGI:END -->"

N = 9
SENTE = "s"
GOTE = "g"

REPO = "kanywst/kanywst"
ASSET = f"https://raw.githubusercontent.com/{REPO}/main/.github/koma"
BODY = "Just+click+Submit+new+issue.+The+board+updates+in+about+30+seconds."

SIDE_NAME = {SENTE: "先手", GOTE: "後手"}
HAND_ORDER = ["R", "B", "G", "S", "N", "L", "P"]
KANJI = {
    "P": "歩", "L": "香", "N": "桂", "S": "銀",
    "G": "金", "B": "角", "R": "飛", "K": "王",
    "+P": "と", "+L": "杏", "+N": "圭", "+S": "全", "+B": "馬", "+R": "龍",
}

RANKS = "abcdefghi"

GOLD = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, 0)]

# 駒ごとの (1 マスだけ動く方向, 何マスでも滑る方向)。先手基準で行が減る向きが前。
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
# 座標。筋は右から 1..9 なので、表示上の左端 (9 筋) が列 0 になる。
# 段は上から a..i で、行 0 が 一段目。
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
# 局面
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
        "games": 0,
        "record": {SENTE: 0, GOTE: 0},
        "players": [],
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        return blank_state()
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    board = state.get("board")
    if not isinstance(board, list) or len(board) != N:
        return blank_state()
    if any(not isinstance(r, list) or len(r) != N for r in board):
        return blank_state()
    return state


# --------------------------------------------------------------------------
# 利き
# --------------------------------------------------------------------------

def destinations(board: list[list[str]], row: int, col: int) -> list[tuple[int, int]]:
    """その駒が動ける升。自分の駒がいる升は除くが、王手放置は見ない。"""
    cell = board[row][col]
    side = side_of(cell)
    kind = kind_of(cell)
    out = []

    # 表の方向は先手基準。後手は前後を反転させる。
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
    """行き所のない駒になる場合は成るしかない。"""
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
    """王手放置を除いた行き先。"""
    board = state["board"]
    side = side_of(board[frm[0]][frm[1]])
    kind = kind_of(board[frm[0]][frm[1]])
    out = []
    for to in destinations(board, *frm):
        # 成らないと行き所が無いなら、成る前提で合法性を見る
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

    # 二歩。同じ筋に成っていない歩があるなら打てない。
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
            # 打ち歩詰め。相手に逃げ道があるかを見るが、その中でさらに
            # 打ち歩詰めを見にいくと再帰が終わらないので、そこでは打ち切る。
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
# 描画
# --------------------------------------------------------------------------

def issue_url(command: str) -> str:
    quoted = command.replace("|", "%7C").replace(" ", "+").replace("*", "%2A")
    return f"https://github.com/{REPO}/issues/new?title=shogi%7C{quoted}&body={BODY}"


def img(name: str, alt: str) -> str:
    # HTML テーブルの中なので markdown の ![]() は展開されない。img で書く。
    return f'<img src="{ASSET}/{name}.svg" width="44" height="48" alt="{alt}">'


def koma_img(cell: str) -> str:
    kind = kind_of(cell)
    return img(side_of(cell) + kind.replace("+", "p"), KANJI[kind])


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

    head = "".join(f"<th>{N - c}</th>" for c in range(N))
    rows = [f"<tr><th></th>{head}</tr>"]

    for r in range(N):
        cells = []
        for c in range(N):
            cell = board[r][c]
            sq = to_sq(r, c)
            inner = koma_img(cell) if cell else img("empty", "")

            if (r, c) in targets:
                link = issue_url(f"mv {selected}{sq}")
                cells.append(f'<td><a href="{link}">{inner if cell else "⭕"}</a></td>')
            elif not over and not state["pending"] and cell and side_of(cell) == turn:
                cells.append(f'<td><a href="{issue_url(f"sel {sq}")}">{inner}</a></td>')
            else:
                cells.append(f"<td>{inner}</td>")
        rows.append(f"<tr><th>{RANKS[r]}</th>{''.join(cells)}</tr>")

    return '<table align="center">\n' + "\n".join(rows) + "\n</table>"


def render_hand(state: dict, side: str) -> str:
    hand = state["hands"].get(side, {})
    held = [(p, n) for p in HAND_ORDER for n in [hand.get(p, 0)] if n > 0]
    if not held:
        return f"{SIDE_NAME[side]}の持ち駒: なし"

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
    return f"{SIDE_NAME[side]}の持ち駒: " + "　".join(parts)


def render(state: dict) -> str:
    turn = state["turn"]
    status = state["status"]
    lines = []

    if status != "playing":
        reason = state.get("reason", "詰み")
        headline = f"{reason}。{SIDE_NAME[state['winner']]}の勝ち。"
    elif state["pending"]:
        headline = "成りますか。"
    elif state["selected"]:
        if state["selected"].startswith("*"):
            headline = f"{KANJI[state['selected'][1:]]}を打ちます。打てる升が ⭕ です。"
        else:
            headline = f"{state['selected']} の駒を選びました。行ける升が ⭕ です。"
    else:
        check = "王手。" if in_check(state["board"], turn) else ""
        headline = f"{check}{SIDE_NAME[turn]}の番です。だれでも指せます。"

    lines.append(f'<p align="center">{headline}</p>')
    lines.append("")
    lines.append(f'<p align="center">{render_hand(state, GOTE)}</p>')
    lines.append("")
    lines.append(render_board(state))
    lines.append("")
    lines.append(f'<p align="center">{render_hand(state, SENTE)}</p>')
    lines.append("")

    if status != "playing":
        call = f'<a href="{issue_url("new")}">次の対局を始める</a>'
    elif state["pending"]:
        yes = issue_url("pro yes")
        no = issue_url("pro no")
        call = f'<a href="{yes}">成る</a>　<a href="{no}">成らず</a>'
    elif state["selected"]:
        call = f'<a href="{issue_url("cancel")}">選び直す</a>'
    else:
        # 詰みまで行かない局面で盤が止まらないよう、投了できるようにしておく
        call = (
            "駒をクリックして、次に行き先をクリック。30 秒ほどで盤が変わります。"
            f'　<a href="{issue_url("resign")}">投了する</a>'
        )

    lines.append(f'<p align="center">{call}</p>')
    lines.append("")

    if state["last"]:
        lines.append(f'<p align="center">前の手: {state["last"]}</p>')
        lines.append("")

    # 通算成績は対局をまたいで残す。1 局終わるたびに消えると記録にならない。
    record = state.get("record", {SENTE: 0, GOTE: 0})
    games = state.get("games", 0)
    played = len(state.get("players", []))
    lines.append(
        f'<p align="center">通算 先手 {record.get(SENTE, 0)}勝　後手 {record.get(GOTE, 0)}勝'
        f'　{games}局　指した人 {played}</p>'
    )
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
# 1 手進める
# --------------------------------------------------------------------------

RANK_KANJI = "一二三四五六七八九"
MARK = {SENTE: "▲", GOTE: "△"}


def describe(state: dict, frm, to, piece_kind: str, promote: bool, dropped: bool) -> str:
    """▲7六歩 の形。棋譜の書き方に合わせて筋は算用数字、段は漢数字。"""
    row, col = to
    square = f"{N - col}{RANK_KANJI[row]}"
    suffix = "打" if dropped else ("成" if promote else "")
    return f"{MARK[state['turn']]}{square}{KANJI[piece_kind]}{suffix}"


def record_win(state: dict, winner: str, reason: str) -> None:
    state["status"] = "over"
    state["winner"] = winner
    state["reason"] = reason
    state["games"] = state.get("games", 0) + 1
    record = state.setdefault("record", {SENTE: 0, GOTE: 0})
    record[winner] = record.get(winner, 0) + 1


def finish_turn(state: dict, note: str) -> str:
    other = GOTE if state["turn"] == SENTE else SENTE
    state["turn"] = other
    state["selected"] = None
    state["pending"] = None

    if is_checkmate(state, other):
        record_win(state, GOTE if other == SENTE else SENTE, "詰み")
        return f"{note} 詰みです。{SIDE_NAME[state['winner']]}の勝ち。"
    if in_check(state["board"], other):
        return f"{note} 王手。"
    return note


def play(state: dict, command: str, user: str) -> str:
    parts = command.split()
    verb = parts[0]

    if verb == "new":
        if state["status"] == "playing":
            return "まだ対局中です。指し手をどうぞ。"
        keep_players = state.get("players", [])
        keep_games = state.get("games", 0)
        keep_record = state.get("record", {SENTE: 0, GOTE: 0})
        fresh = blank_state()
        fresh["players"] = keep_players
        fresh["games"] = keep_games
        fresh["record"] = keep_record
        state.clear()
        state.update(fresh)
        return "新しい盤面です。先手からどうぞ。"

    if state["status"] != "playing":
        return "この対局はもう終わっています。新しい対局を始めてください。"

    if verb == "resign":
        loser = state["turn"]
        winner = GOTE if loser == SENTE else SENTE
        state["last"] = f"{MARK[loser]}投了"
        record_win(state, winner, "投了")
        state["selected"] = None
        state["pending"] = None
        return f"{SIDE_NAME[loser]}の投了です。{SIDE_NAME[winner]}の勝ち。"

    if verb == "cancel":
        state["selected"] = None
        state["pending"] = None
        return "選択をやめました。"

    if verb == "sel":
        if state["pending"]:
            return "先に成るかどうかを決めてください。"
        target = parts[1]
        if target.startswith("*"):
            piece = target[1:]
            if state["hands"][state["turn"]].get(piece, 0) < 1:
                return f"{KANJI.get(piece, piece)}は持っていません。"
            if not legal_drops(state, piece):
                return f"{KANJI[piece]}を打てる升がありません。"
        else:
            row, col = from_sq(target)
            cell = state["board"][row][col]
            if not cell or side_of(cell) != state["turn"]:
                return f"{target} に{SIDE_NAME[state['turn']]}の駒がありません。"
            if not legal_moves_from(state, (row, col)):
                return f"{target} の駒は動けません。"
        state["selected"] = target
        return "選びました。行き先をクリックしてください。"

    if verb == "mv":
        selected = state["selected"]
        if not selected:
            return "先に駒を選んでください。"
        arg = parts[1]

        if selected.startswith("*"):
            piece = selected[1:]
            to = from_sq(arg[-2:])
            if to not in legal_drops(state, piece):
                return "そこには打てません。"
            state["board"][to[0]][to[1]] = state["turn"] + piece
            state["hands"][state["turn"]][piece] -= 1
            if state["hands"][state["turn"]][piece] == 0:
                del state["hands"][state["turn"]][piece]
            state["last"] = describe(state, None, to, piece, False, True)
            state["selected"] = None
            return finish_turn(state, f"{state['last']}。")

        frm = from_sq(selected)
        to = from_sq(arg[-2:])
        if to not in legal_moves_from(state, frm):
            return "そこへは動けません。"

        kind = kind_of(state["board"][frm[0]][frm[1]])
        if must_promote(kind, to[0], state["turn"]):
            apply_move(state["board"], state["hands"], frm, to, True)
            state["last"] = describe(state, frm, to, kind, True, False)
            state["selected"] = None
            return finish_turn(state, f"{state['last']}。")

        if can_promote(kind, frm[0], to[0], state["turn"]):
            state["pending"] = {"from": selected, "to": to_sq(*to)}
            return "成るかどうかを選んでください。"

        apply_move(state["board"], state["hands"], frm, to, False)
        state["last"] = describe(state, frm, to, kind, False, False)
        state["selected"] = None
        return finish_turn(state, f"{state['last']}。")

    if verb == "pro":
        if not state["pending"]:
            return "いま成るかどうかを聞かれていません。"
        promote = parts[1] == "yes"
        frm = from_sq(state["pending"]["from"])
        to = from_sq(state["pending"]["to"])
        kind = kind_of(state["board"][frm[0]][frm[1]])
        apply_move(state["board"], state["hands"], frm, to, promote)
        state["last"] = describe(state, frm, to, kind, promote, False)
        state["pending"] = None
        state["selected"] = None
        return finish_turn(state, f"{state['last']}。")

    return f"'{command}' は指し手として読めません。"


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
        sys.exit(f"'{title}' is not a shogi command")

    state = load_state()
    message = play(state, command, user)

    if command not in ("new", "cancel") and user not in state["players"]:
        state["players"].append(user)

    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    write_readme(state)
    print(message)


if __name__ == "__main__":
    main()
