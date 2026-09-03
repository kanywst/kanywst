#!/usr/bin/env python3
"""
make_cards.py

Draws the blackjack table images (.github/cards/*.svg). Run by hand once, never
from the Action.

Every tile paints its own felt background. Nothing else can: GitHub strips style
from README HTML, so a row of cards cannot be given a background, and a
transparent tile would take the colour of GitHub's image placeholder. Painting
the felt into each tile is what makes a row of separate images read as one
table, the same trick the shogi board used to look like a board.

The suits are paths rather than the ♠♥♦♣ characters. An SVG loaded through
<img> resolves fonts on the reader's machine, and those four characters differ
wildly between platforms — some render them as emoji. The ranks are text, since
digits and A/J/Q/K are safe everywhere, but every string is drawn with
textLength so a wider font cannot push it out of the card.
"""

import pathlib

OUT = pathlib.Path(".github/cards")

# A card tile. The card itself is inset, so the felt shows as a gap between
# neighbours and a hand reads as cards laid on a table.
W, H = 44, 62

FELT = "#1c5c43"
FELT_LINE = "#14472f"

FACE = "#fbf9f4"
FACE_EDGE = "#d8d2c4"
INK = "#1f2328"
RED = "#b3261e"

# The back of a card, and the frame that says which hand is being played. Both
# borrow the shogi board's palette so the two games sit on one profile.
BACK = "#8b1f2f"
BACK_LINE = "#6d1724"
MARKER = "#c1121f"

# Buttons and the table sign are the shogi piece's wood, for the same reason.
WOOD = "#f0d9a8"
WOOD_EDGE = "#8b6f47"

# What a real table has printed on the cloth: readable, and quieter than a card.
PRINT = "#8fb3a0"

FONT = "'Helvetica Neue',Helvetica,Arial,'Liberation Sans',sans-serif"

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
LABEL = {"T": "10"}
SUITS = {"S": "spade", "H": "heart", "D": "diamond", "C": "club"}
RED_SUITS = ("H", "D")

# Each suit drawn inside a 24x24 box, so one scale factor places it anywhere.
SUIT_PATHS = {
    "S": ('<path d="M12 2C12 2 3.6 9.2 3.6 14.4a4.6 4.6 0 0 0 7.5 3.6c-.2 1.4-1.2 3.4-2.7 4.8h7.2'
          'c-1.5-1.4-2.5-3.4-2.7-4.8a4.6 4.6 0 0 0 7.5-3.6C20.4 9.2 12 2 12 2Z" fill="{ink}"/>'),
    "H": ('<path d="M12 21.6S3 14.8 3 9.2A4.9 4.9 0 0 1 12 6.4 4.9 4.9 0 0 1 21 9.2'
          'c0 5.6-9 12.4-9 12.4Z" fill="{ink}"/>'),
    "D": '<path d="M12 1.6 20.4 12 12 22.4 3.6 12Z" fill="{ink}"/>',
    "C": ('<g fill="{ink}"><circle cx="12" cy="7.4" r="4.2"/><circle cx="6.9" cy="14.4" r="4.2"/>'
          '<circle cx="17.1" cy="14.4" r="4.2"/>'
          '<path d="M10.9 13.2h2.2c0 4.2.6 7.2 2.6 9.2h-7.4c2-2 2.6-5 2.6-9.2Z"/></g>'),
}

# value -> (face, edge, ink). The colours a real rack uses, as far as the
# denominations here overlap with one.
CHIPS = {
    1: ("#f7f4ee", "#cfc9bb", INK),
    2: ("#d98ca6", "#b26c84", INK),
    5: ("#c1272d", "#8e1c21", "#fdf7f7"),
    10: ("#2f5fa8", "#22467c", "#f4f7fd"),
    25: ("#2e7d4f", "#1f5a38", "#f4faf6"),
}

BUTTONS = ["hit", "stand", "double", "split", "surrender", "insure", "no"]
BUTTON_H = 30


def head(w: int, h: int, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}"'
            f' width="{w}" height="{h}" role="img" aria-label="{label}">')


def felt(w: int, h: int) -> str:
    return f'\n  <rect width="{w}" height="{h}" fill="{FELT}"/>'


def pip(suit: str, cx: float, cy: float, size: float, ink: str) -> str:
    """A suit centred on (cx, cy), size being the width of its 24-unit box."""
    k = size / 24
    return (f'\n  <g transform="translate({cx - size / 2:.2f} {cy - size / 2:.2f})'
            f' scale({k:.4f})">{SUIT_PATHS[suit].format(ink=ink)}</g>')


def text(body: str, x: float, y: float, size: float, ink: str, width: float) -> str:
    """Text pinned to an exact width, because the reader's fonts are unknown."""
    return (f'\n  <text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}"'
            f' font-weight="700" fill="{ink}" text-anchor="middle"'
            f' textLength="{width}" lengthAdjust="spacingAndGlyphs">{body}</text>')


def card(rank: str, suit: str) -> str:
    ink = RED if suit in RED_SUITS else INK
    label = LABEL.get(rank, rank)
    name = f"{'ten' if rank == 'T' else label} of {SUITS[suit]}s"
    # The corner index is narrower for the ten, so a two-character rank does not
    # crowd the pip under it.
    index_width = 13 if rank == "T" else 9
    return (
        head(W, H, name)
        + felt(W, H)
        + f'\n  <rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4"'
          f' fill="{FACE}" stroke="{FACE_EDGE}"/>'
        + text(label, 11, 18, 14, ink, index_width)
        + pip(suit, 11, 26, 9, ink)
        + pip(suit, 26, 42, 25, ink)
        + "\n</svg>\n"
    )


def back() -> str:
    """The hole card. A pattern, not a flat colour, so it reads as face down."""
    lines = "".join(
        f'\n    <path d="M{x} 6 L{x + 14} {H - 6}" />' for x in range(-8, W + 8, 7)
    )
    return (
        head(W, H, "face down card")
        + felt(W, H)
        + '\n  <clipPath id="card">'
          f'<rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4"/></clipPath>'
        + f'\n  <rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4" fill="{BACK}"/>'
        + f'\n  <g clip-path="url(#card)" stroke="{BACK_LINE}" stroke-width="2.5">{lines}\n  </g>'
        + f'\n  <rect x="2.5" y="2.5" width="{W - 5}" height="{H - 5}" rx="4"'
          f' fill="none" stroke="{FACE}" stroke-width="2"/>'
        + "\n</svg>\n"
    )


def blank() -> str:
    """Felt and nothing else, to pad a short row out to the width of the
    longest one. Rows are centred, so without it a split hand staggers."""
    return head(W, H, "") + felt(W, H) + "\n</svg>\n"


def slot() -> str:
    """Where a card will be dealt. Without it the table collapses to nothing
    between hands, and the section jumps by two card-heights on every deal."""
    return (
        head(W, H, "empty card slot")
        + felt(W, H)
        + f'\n  <rect x="3" y="3" width="{W - 6}" height="{H - 6}" rx="4" fill="none"'
          f' stroke="{FELT_LINE}" stroke-width="1.5" stroke-dasharray="4 4"/>'
        + "\n</svg>\n"
    )


def chip(value: int, selected: bool = False) -> str:
    face, edge, ink = CHIPS[value]
    size = 44
    c = size / 2
    # The spots on the rim, which is what says chip rather than coin.
    spots = "".join(
        f'\n    <rect x="{c - 2.6}" y="1.6" width="5.2" height="6" rx="1.6"'
        f' transform="rotate({angle} {c} {c})"/>'
        for angle in range(0, 360, 45)
    )
    frame = (f'\n  <rect x="1.25" y="1.25" width="{size - 2.5}" height="{size - 2.5}"'
             f' fill="none" stroke="{MARKER}" stroke-width="2.5"/>' if selected else "")
    return (
        head(size, size, f"bet {value} unit{'' if value == 1 else 's'}")
        + felt(size, size)
        + f'\n  <circle cx="{c}" cy="{c}" r="{c - 3}" fill="{face}" stroke="{edge}"'
          f' stroke-width="1.5"/>'
        + f'\n  <g fill="{edge}">{spots}\n  </g>'
        + f'\n  <circle cx="{c}" cy="{c}" r="{c - 9}" fill="{face}" stroke="{edge}"/>'
        + text(str(value), c, c + 5, 15, ink, 9 if value < 10 else 17)
        + frame
        + "\n</svg>\n"
    )


def button(label: str) -> str:
    body = label.upper()
    # Wide enough for the label at 8.4 units a character, which is what the
    # textLength below then holds it to.
    inner = round(len(body) * 8.4)
    w = inner + 24
    return (
        head(w, BUTTON_H, label)
        + felt(w, BUTTON_H)
        + f'\n  <rect x="2" y="3" width="{w - 4}" height="{BUTTON_H - 6}" rx="4"'
          f' fill="{WOOD}" stroke="{WOOD_EDGE}" stroke-width="1.5"/>'
        + text(body, w / 2, BUTTON_H / 2 + 4, 12, INK, inner)
        + "\n</svg>\n"
    )


def seat(word: str, active: bool = False) -> str:
    """Whose row this is, printed on the felt at the head of it.

    A real table has its layout printed on the cloth, and this one needs it more
    than most: the only other thing saying which row belongs to the dealer is a
    sentence underneath, and a reader should not have to find a sentence to read
    a table. The frame marks which of several split hands is in play, since a
    red frame around the cards themselves would mean drawing all 52 twice.
    """
    w = 52
    frame = (f'\n  <rect x="2.25" y="2.25" width="{w - 4.5}" height="{H - 4.5}" fill="none"'
             f' stroke="{MARKER}" stroke-width="3"/>' if active else "")
    body = word.upper()
    inner = round(len(body) * 6.4)
    return (head(w, H, word + (" in play" if active else ""))
            + felt(w, H)
            + f'\n  <text x="{w / 2}" y="{H / 2 + 4}" font-family="{FONT}" font-size="9"'
              f' font-weight="700" letter-spacing="1" fill="{PRINT}" text-anchor="middle"'
              f' textLength="{inner}" lengthAdjust="spacingAndGlyphs">{body}</text>'
            + frame
            + "\n</svg>\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0

    def write(name: str, body: str) -> None:
        nonlocal written
        (OUT / f"{name}.svg").write_text(body, encoding="utf-8")
        written += 1

    for rank in RANKS:
        for suit in SUITS:
            write(f"{rank}{suit}", card(rank, suit))

    write("back", back())
    write("slot", slot())
    write("blank", blank())

    for value in CHIPS:
        write(f"chip{value}", chip(value))

    for label in BUTTONS:
        write(f"btn-{label}", button(label))

    write("label-dealer", seat("dealer"))
    write("label-you", seat("you"))
    write("label-you-sel", seat("you", active=True))

    print(f"wrote {written} files to {OUT}")


if __name__ == "__main__":
    main()
