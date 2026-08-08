#!/usr/bin/env python3
"""
connect_four.py

GitHub Actions から呼び出され、Issue のタイトルを 1 手として盤面に反映し、
README.md の CONNECT4 マーカー間を描き直す。

ゲストブックと同じ仕組み (Issue を立てる → Action → マーカー間を書き換え) で、
新しい機構は増やしていない。

Issue タイトル:
  connect4|1 .. connect4|7 - その列に落とす
  connect4|new             - 決着済みの盤を片付けて次を始める

環境変数:
  ISSUE_TITLE  - Issue タイトル
  ISSUE_USER   - Issue 作成者
  ISSUE_NUMBER - Issue 番号 (未使用だが Action 側と揃えて渡す)

標準出力の最終行を Action が Issue へのコメントとして使う。
"""

import json
import os
import pathlib
import re
import sys

README_PATH = pathlib.Path("README.md")
STATE_PATH = pathlib.Path(".github/connect_four.json")

START_MARKER = "<!-- CONNECT4:START -->"
END_MARKER = "<!-- CONNECT4:END -->"

ROWS = 6
COLS = 7

RED = "r"
YELLOW = "y"
EMPTY = ""

NAME = {RED: "Red", YELLOW: "Yellow"}
PIP = {RED: "🔴", YELLOW: "🟡"}

REPO = "kanywst/kanywst"

# 盤面は絵文字ではなく画像で描く。⚪ はライトテーマの白地でほとんど見えないし、
# 端末やフォントによって大きさが揃わない。JonathanGin52 の Connect Four も
# 同じ理由で画像を使っている。空きマスの灰色はライト・ダークどちらでも読める
# 中間色にしてあるので、セルごとに <picture> を持たせずに済む。
ASSET = "https://raw.githubusercontent.com/kanywst/kanywst/main/.github"
DISC = {
    RED: f"![red]({ASSET}/c4-red.svg)",
    YELLOW: f"![yellow]({ASSET}/c4-yellow.svg)",
    EMPTY: f"![ ]({ASSET}/c4-empty.svg)",
}
BODY = "Just+click+Submit+new+issue.+The+board+updates+in+about+30+seconds."


def move_url(column: int) -> str:
    return f"https://github.com/{REPO}/issues/new?title=connect4%7C{column}&body={BODY}"


def new_game_url() -> str:
    return f"https://github.com/{REPO}/issues/new?title=connect4%7Cnew&body={BODY}"


def blank_state() -> dict:
    return {
        "board": [[EMPTY] * COLS for _ in range(ROWS)],
        "turn": RED,
        "status": "playing",
        "winner": None,
        "games": 0,
        "players": [],
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        return blank_state()
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    # 盤の形が壊れている状態で描画に進むより、作り直した方が安全
    board = state.get("board")
    if not isinstance(board, list) or len(board) != ROWS:
        return blank_state()
    if any(not isinstance(row, list) or len(row) != COLS for row in board):
        return blank_state()
    return state


def drop(board: list[list[str]], column: int, disc: str) -> int:
    """列の一番下の空きに落とし、その行番号を返す。満杯なら -1。"""
    for row in range(ROWS - 1, -1, -1):
        if board[row][column] == EMPTY:
            board[row][column] = disc
            return row
    return -1


def wins(board: list[list[str]], row: int, col: int) -> bool:
    """置いたばかりの石を通る 4 連があるか調べる。"""
    disc = board[row][col]
    for drow, dcol in ((0, 1), (1, 0), (1, 1), (1, -1)):
        count = 1
        for step in (1, -1):
            r, c = row + drow * step, col + dcol * step
            while 0 <= r < ROWS and 0 <= c < COLS and board[r][c] == disc:
                count += 1
                r += drow * step
                c += dcol * step
        if count >= 4:
            return True
    return False


def full(board: list[list[str]]) -> bool:
    return all(cell != EMPTY for cell in board[0])


def render(state: dict) -> str:
    board = state["board"]
    over = state["status"] != "playing"

    # 決着後に列番号がリンクのままだと押せてしまうので、ただの数字に落とす
    if over:
        header = "| " + " | ".join(str(c + 1) for c in range(COLS)) + " |"
    else:
        header = (
            "| " + " | ".join(f"[{c + 1}]({move_url(c + 1)})" for c in range(COLS)) + " |"
        )

    lines = [header, "| " + " | ".join([":-:"] * COLS) + " |"]
    for row in board:
        lines.append("| " + " | ".join(DISC[cell] for cell in row) + " |")

    if state["status"] == "won":
        headline = f"{PIP[state['winner']]} {NAME[state['winner']]} won."
        call = f"[Start a new game]({new_game_url()})"
    elif state["status"] == "draw":
        headline = "A draw. Every square is full."
        call = f"[Start a new game]({new_game_url()})"
    else:
        turn = state["turn"]
        headline = f"{PIP[turn]} {NAME[turn]} to play. Anyone can take the turn."
        call = "Click a number to drop a disc. It lands in about 30 seconds."

    games = state.get("games", 0)
    played = len(state.get("players", []))
    tally = (
        f"{games} {'game' if games == 1 else 'games'} finished, "
        f"{played} {'person has' if played == 1 else 'people have'} played."
    )

    return "\n".join([headline, "", *lines, "", call, "", tally])


def write_readme(state: dict) -> None:
    content = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )
    if not pattern.search(content):
        raise SystemExit("CONNECT4 markers not found in README.md")

    block = f"{START_MARKER}\n{render(state)}\n{END_MARKER}"
    README_PATH.write_text(pattern.sub(lambda _: block, content), encoding="utf-8")


def parse_move(title: str) -> str | None:
    match = re.search(r"connect4\s*\|\s*(new|[1-7])", title, re.IGNORECASE)
    return match.group(1).lower() if match else None


def main() -> None:
    title = os.environ.get("ISSUE_TITLE", "")
    user = os.environ.get("ISSUE_USER", "someone")

    move = parse_move(title)
    if move is None:
        sys.exit(f"'{title}' is not a connect4 move")

    state = load_state()

    if move == "new":
        if state["status"] == "playing":
            message = "That game is still going. Take a turn instead of restarting it."
        else:
            players = state.get("players", [])
            games = state.get("games", 0)
            state = blank_state()
            state["players"] = players
            state["games"] = games
            message = "New board. Red goes first."
    elif state["status"] != "playing":
        message = "That game is already over. Start a new one and I'll deal again."
    else:
        column = int(move) - 1
        disc = state["turn"]
        row = drop(state["board"], column, disc)
        if row < 0:
            message = f"Column {move} is full. Pick another one."
        else:
            if user not in state["players"]:
                state["players"].append(user)

            if wins(state["board"], row, column):
                state["status"] = "won"
                state["winner"] = disc
                state["games"] = state.get("games", 0) + 1
                message = f"{PIP[disc]} {NAME[disc]} wins, and you played the last disc."
            elif full(state["board"]):
                state["status"] = "draw"
                state["games"] = state.get("games", 0) + 1
                message = "That fills the board. It's a draw."
            else:
                state["turn"] = YELLOW if disc == RED else RED
                message = f"Dropped in column {move}. {NAME[state['turn']]} is up."

    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    write_readme(state)
    print(message)


if __name__ == "__main__":
    main()
