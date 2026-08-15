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

Every piece is written a third time in a drained palette, for the side that is
not to move. Which side is which, and which of them moves next, then reads off
the board itself without a word of English on it, and the pieces that carry
their colour are exactly the ones worth clicking.

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

# The waiting side. The same piece with the warmth taken out of it, dark enough
# against the square to stay a piece rather than an empty space.
IDLE_FACE = "#e2dbcd"
IDLE_EDGE = "#a99f8d"
IDLE_INK = "#6f6a62"
IDLE_PROMOTED_INK = "#a37f79"

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


def svg(label: str, promoted: bool, gote: bool, selected: bool = False,
        idle: bool = False) -> str:
    koma_face = IDLE_FACE if idle else FACE
    koma_edge = IDLE_EDGE if idle else EDGE
    if idle:
        ink = IDLE_PROMOTED_INK if promoted else IDLE_INK
    else:
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
    <polygon points="{POINTS}" fill="{koma_face}" stroke="{koma_edge}" stroke-width="1.5" stroke-linejoin="round"/>
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
            # A waiting piece is never the selected one, so there is no
            # -idle-sel to draw.
            for suffix, selected, idle in (("", False, False),
                                           ("-sel", True, False),
                                           ("-idle", False, True)):
                path = OUT / f"{side}{name}{suffix}.svg"
                path.write_text(svg(text, promoted, gote, selected, idle), encoding="utf-8")
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
