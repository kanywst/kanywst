#!/usr/bin/env python3
"""
make_koma.py

将棋の駒画像 (.github/koma/*.svg) を生成する。一度だけ走らせる類のもので、
Action からは呼ばれない。

Wikimedia Commons には未成駒 9 種の写真しかなく、成駒も後手向きの駒も無いため、
14 種 × 先後 2 向き = 28 枚をここで描く。五角形は駒の形そのままで、後手の駒は
180 度回転させる。盤上でどちらの駒か分かる方法は向きしかないため。

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


def svg(label: str, promoted: bool, gote: bool) -> str:
    ink = PROMOTED_INK if promoted else INK
    # 後手の駒は盤ごと 180 度回して置くので、駒も回す
    rotate = f' transform="rotate(180 {W / 2} {H / 2})"' if gote else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{label}">
  <g{rotate}>
    <polygon points="{POINTS}" fill="{FACE}" stroke="{EDGE}" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="{W / 2}" y="34" font-family="{FONT}" font-size="24" fill="{ink}" text-anchor="middle">{label}</text>
  </g>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    written = 0
    for piece, (label, promoted) in PIECES.items():
        for side, gote in (("s", False), ("g", True)):
            name = piece.replace("+", "p")
            text = "玉" if piece == "K" and gote else label
            path = OUT / f"{side}{name}.svg"
            path.write_text(svg(text, promoted, gote), encoding="utf-8")
            written += 1

    # 空マス。盤の升目だけを描く。
    (OUT / "empty.svg").write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="empty">
  <rect width="{W}" height="{H}" fill="none"/>
</svg>
""",
        encoding="utf-8",
    )
    print(f"wrote {written + 1} files to {OUT}")


if __name__ == "__main__":
    main()
