#!/usr/bin/env python3
"""
make_koma.py

将棋の駒画像 (.github/koma/*.svg) を生成する。一度だけ走らせる類のもので、
Action からは呼ばれない。

Wikimedia Commons には未成駒 9 種の写真しかなく、成駒も後手向きの駒も無いため、
14 種 × 先後 2 向き = 28 枚をここで描く。五角形は駒の形そのままで、後手の駒は
180 度回転させる。盤上でどちらの駒か分かる方法は向きしかないため。

The same 28 are written again as "selected" variants with a red frame. GitHub strips
style attributes from README HTML, so a square cannot be highlighted with CSS.
Swapping the image is the only way to show which piece is selected.

Both kings are written a third time as "-turn" variants, framed in a pulsing blue.
A single line of text above the board is easy to miss; SMIL inside an SVG animates
even through <img>, the same trick as the blinking wordmark cursor.

成駒の字を朱にするのは実際の駒と同じ。
"""

import pathlib

OUT = pathlib.Path(".github/koma")

W, H = 44, 48

# 五角形。上が尖った駒の形。
POINTS = "22,3 37,11 40,45 4,45 7,11"

INK = "#1f2328"
PROMOTED_INK = "#b3261e"
FACE = "#f0d9a8"
EDGE = "#8b6f47"
CELL = "#f7efdc"
SELECTED_CELL = "#fbe0d5"
MARKER = "#c1121f"
# Not the marker red: a turn frame in that colour reads as "selected".
TURN_CELL = "#e4eefa"
TURN_MARKER = "#0f5ba8"

# CJK フォントは環境ごとに名前が違うので、実在しそうなものを順に並べて
# 最後に総称 serif へ落とす。<img> で読み込まれた SVG は閲覧者側の
# フォントで解決されるため、特定の 1 つに賭けられない。
FONT = "'Hiragino Mincho ProN','Yu Mincho','YuMincho','Noto Serif CJK JP','Noto Serif JP','Source Han Serif JP','MS Mincho',serif"

# 駒 ID -> (表記, 成駒か)
PIECES = {
    "P": ("歩", False),
    "L": ("香", False),
    "N": ("桂", False),
    "S": ("銀", False),
    "G": ("金", False),
    "B": ("角", False),
    "R": ("飛", False),
    # 先手が王将、後手が玉将。実際の駒と同じ。
    "K": ("王", False),
    "+P": ("と", True),
    "+L": ("杏", True),
    "+N": ("圭", True),
    "+S": ("全", True),
    "+B": ("馬", True),
    "+R": ("龍", True),
}


def svg(label: str, promoted: bool, gote: bool, selected: bool = False,
        turn: bool = False) -> str:
    ink = PROMOTED_INK if promoted else INK
    # 後手の駒は盤ごと 180 度回して置くので、駒も回す
    rotate = f' transform="rotate(180 {W / 2} {H / 2})"' if gote else ""
    face = SELECTED_CELL if selected else (TURN_CELL if turn else CELL)
    frame = ""
    aria = label
    if selected:
        # The same red as the move markers, so that "this piece goes to those
        # circles" reads at a glance.
        frame = (f'\n  <rect x="2.25" y="2.25" width="{W - 4.5}" height="{H - 4.5}" fill="none"'
                 f' stroke="{MARKER}" stroke-width="3"/>')
        aria = f"{label} selected"
    elif turn:
        # A still frame gets lost in the grid; the pulse is what catches the eye.
        frame = (f'\n  <rect x="2.25" y="2.25" width="{W - 4.5}" height="{H - 4.5}" fill="none"'
                 f' stroke="{TURN_MARKER}" stroke-width="3">'
                 f'\n    <animate attributeName="opacity" values="1;0.25;1"'
                 f' dur="2.4s" repeatCount="indefinite"/>'
                 f'\n  </rect>')
        aria = f"{label} to move"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{aria}">
  <rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" fill="{face}" stroke="{EDGE}" stroke-width="1.5"/>
  <g{rotate}>
    <polygon points="{POINTS}" fill="{FACE}" stroke="{EDGE}" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="{W / 2}" y="34" font-family="{FONT}" font-size="24" fill="{ink}" text-anchor="middle">{label}</text>
  </g>{frame}
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for piece, (label, promoted) in PIECES.items():
        for side, gote in (("s", False), ("g", True)):
            name = piece.replace("+", "p")
            text = "玉" if piece == "K" and gote else label
            variants = [("", False, False), ("-sel", True, False)]
            if piece == "K":
                variants.append(("-turn", False, True))
            for suffix, selected, turn in variants:
                path = OUT / f"{side}{name}{suffix}.svg"
                path.write_text(svg(text, promoted, gote, selected, turn), encoding="utf-8")
                written += 1

    # 空マスと移動先。盤の枠は自分で描く。透明にしておくと、盤の格子が
    # GitHub の画像プレースホルダの背景色に依存してしまう。
    for name, extra in (
        ("empty", ""),
        ("target", f'<circle cx="{W / 2}" cy="{H / 2}" r="9" fill="none" stroke="{MARKER}" stroke-width="4"/>'),
    ):
        (OUT / f"{name}.svg").write_text(
            f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{name}">
  <rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" fill="{CELL}" stroke="{EDGE}" stroke-width="1.5"/>
  {extra}
</svg>
""",
            encoding="utf-8",
        )
        written += 1
    print(f"wrote {written} files to {OUT}")


if __name__ == "__main__":
    main()
