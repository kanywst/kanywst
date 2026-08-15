#!/usr/bin/env python3
"""
make_koma.py

Draws the shogi piece images (.github/koma/*.svg). Run by hand once, never from
the Action.

Wikimedia Commons only has photographs of the 9 unpromoted pieces, with nothing
promoted and nothing facing the other way, so all 14 kinds x 2 directions = 28
are drawn here. The pentagon is the shape of a real piece; White's are turned
180 degrees, since orientation is the only thing that says whose piece it is.

The same 28 are written again as "selected" variants with a red frame. GitHub strips
style attributes from README HTML, so a square cannot be highlighted with CSS.
Swapping the image is the only way to show which piece is selected.

It also draws the two name plates that sit above and below the board. The plate
of the side to move is inked dark, the waiting one is left pale, so whose turn it
is reads from across the page and from the side of the board it belongs to.

Promoted pieces are inked in red, as they are on a real board.
"""

import pathlib

OUT = pathlib.Path(".github/koma")

W, H = 44, 48

# The pentagon, pointed end up.
POINTS = "22,3 37,11 40,45 4,45 7,11"

INK = "#1f2328"
PROMOTED_INK = "#b3261e"
FACE = "#f0d9a8"
EDGE = "#8b6f47"
CELL = "#f7efdc"
SELECTED_CELL = "#fbe0d5"
MARKER = "#c1121f"

# The name plates. Ink and paper rather than a second accent colour: the red is
# already spoken for by selection and move markers.
PLATE_W, PLATE_H = W * 9, 40
PLATE_INKED = "#5a4632"
PLATE_INKED_EDGE = "#3f3226"
PLATE_PAPER_EDGE = "#c9b48d"
PLATE_PAPER_INK = "#8a7660"

# CJK fonts are named differently on every platform, so the likely ones are
# listed in order and fall back to generic serif. An SVG loaded through <img>
# resolves fonts on the reader's machine, so no single name can be relied on.
FONT = "'Hiragino Mincho ProN','Yu Mincho','YuMincho','Noto Serif CJK JP','Noto Serif JP','Source Han Serif JP','MS Mincho',serif"

# piece id -> (label, promoted)
PIECES = {
    "P": ("歩", False),
    "L": ("香", False),
    "N": ("桂", False),
    "S": ("銀", False),
    "G": ("金", False),
    "B": ("角", False),
    "R": ("飛", False),
    # Black gets 王将 and White 玉将, as on a real set.
    "K": ("王", False),
    "+P": ("と", True),
    "+L": ("杏", True),
    "+N": ("圭", True),
    "+S": ("全", True),
    "+B": ("馬", True),
    "+R": ("龍", True),
}


def svg(label: str, promoted: bool, gote: bool, selected: bool = False) -> str:
    ink = PROMOTED_INK if promoted else INK
    # White sits across the board, so the piece is turned with it.
    rotate = f' transform="rotate(180 {W / 2} {H / 2})"' if gote else ""
    # The selected square is framed in the same red as the move markers, so that
    # "this piece goes to those circles" reads at a glance.
    face = SELECTED_CELL if selected else CELL
    frame = (f'\n  <rect x="2.25" y="2.25" width="{W - 4.5}" height="{H - 4.5}" fill="none"'
             f' stroke="{MARKER}" stroke-width="3"/>' if selected else "")
    aria = f"{label} selected" if selected else label
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{aria}">
  <rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" fill="{face}" stroke="{EDGE}" stroke-width="1.5"/>
  <g{rotate}>
    <polygon points="{POINTS}" fill="{FACE}" stroke="{EDGE}" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="{W / 2}" y="34" font-family="{FONT}" font-size="24" fill="{ink}" text-anchor="middle">{label}</text>
  </g>{frame}
</svg>
"""


def plate(side: str, state: str) -> str:
    """A name plate, as wide as the board. state is idle, turn or win."""
    mark = "▲" if side == "s" else "△"
    name = "BLACK" if side == "s" else "WHITE"
    label = {"idle": f"{mark} {name}",
             "turn": f"{mark} {name} · to move",
             "win": f"{mark} {name} · wins"}[state]
    inked = state != "idle"
    face = PLATE_INKED if inked else CELL
    edge = PLATE_INKED_EDGE if inked else PLATE_PAPER_EDGE
    ink = CELL if inked else PLATE_PAPER_INK
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {PLATE_W} {PLATE_H}" width="{PLATE_W}" height="{PLATE_H}" role="img" aria-label="{label}">
  <rect x="0.75" y="0.75" width="{PLATE_W - 1.5}" height="{PLATE_H - 1.5}" fill="{face}" stroke="{edge}" stroke-width="1.5"/>
  <text x="{PLATE_W / 2}" y="26" font-family="{FONT}" font-size="17" letter-spacing="2" fill="{ink}" text-anchor="middle">{label}</text>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for piece, (label, promoted) in PIECES.items():
        for side, gote in (("s", False), ("g", True)):
            name = piece.replace("+", "p")
            text = "玉" if piece == "K" and gote else label
            for suffix, selected in (("", False), ("-sel", True)):
                path = OUT / f"{side}{name}{suffix}.svg"
                path.write_text(svg(text, promoted, gote, selected), encoding="utf-8")
                written += 1

    for side in ("s", "g"):
        for suffix, state in (("", "idle"), ("-turn", "turn"), ("-win", "win")):
            (OUT / f"plate-{side}{suffix}.svg").write_text(plate(side, state), encoding="utf-8")
            written += 1

    # Empty squares and move targets, each drawing its own border. Left
    # transparent, the grid would take the colour of GitHub's image placeholder.
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
