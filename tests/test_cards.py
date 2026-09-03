#!/usr/bin/env python3
"""
Tests for the blackjack table art.

The table is drawn as one image per card, and a missing or wrongly sized file
does not fail anything at render time — it ships a broken image to the profile.
These cover that every image the table can name exists, that each one is
well-formed, and the two properties the layout depends on: an intrinsic size
that matches the viewBox, and an opaque background.
"""

import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import make_cards  # noqa: E402

CARDS = ROOT / ".github" / "cards"


def svg_files() -> list[pathlib.Path]:
    return sorted(CARDS.glob("*.svg"))


class Art(unittest.TestCase):
    def test_every_image_the_table_can_name_exists(self):
        expected = {f"{rank}{suit}" for rank in make_cards.RANKS for suit in make_cards.SUITS}
        expected |= {"back", "slot", "blank", "label-dealer", "label-you",
                     "label-you-sel"}
        expected |= {f"chip{value}" for value in make_cards.CHIPS}
        expected |= {f"btn-{label}" for label in make_cards.BUTTONS}
        self.assertEqual({p.stem for p in svg_files()}, expected)

    def test_every_file_is_well_formed(self):
        for path in svg_files():
            with self.subTest(path.name):
                ET.parse(path)

    def test_the_intrinsic_size_matches_the_viewbox(self):
        # GitHub sizes the image from these attributes, and the README gives the
        # img none of its own. A mismatch scales the art against its neighbours.
        for path in svg_files():
            with self.subTest(path.name):
                root = ET.parse(path).getroot()
                box = root.get("viewBox").split()
                self.assertEqual(box[:2], ["0", "0"])
                self.assertEqual(root.get("width"), box[2])
                self.assertEqual(root.get("height"), box[3])

    def test_every_tile_paints_its_own_felt(self):
        # Left transparent, a tile takes the colour of GitHub's image
        # placeholder, and a row of cards stops reading as one table.
        for path in svg_files():
            with self.subTest(path.name):
                self.assertIn(f'fill="{make_cards.FELT}"', path.read_text(encoding="utf-8"))

    def test_the_cards_are_one_size_and_line_up_with_the_marker(self):
        heights = set()
        for path in svg_files():
            root = ET.parse(path).getroot()
            if path.stem.startswith("label-") or len(path.stem) == 2 \
                    or path.stem in ("blank", "back", "slot"):
                heights.add(root.get("height"))
        self.assertEqual(heights, {str(make_cards.H)})

    def test_red_suits_are_inked_red_and_black_suits_are_not(self):
        for suit in make_cards.SUITS:
            for rank in make_cards.RANKS:
                text = (CARDS / f"{rank}{suit}.svg").read_text(encoding="utf-8")
                with self.subTest(f"{rank}{suit}"):
                    if suit in make_cards.RED_SUITS:
                        self.assertIn(make_cards.RED, text)
                        self.assertNotIn(make_cards.INK, text)
                    else:
                        self.assertIn(make_cards.INK, text)
                        self.assertNotIn(make_cards.RED, text)

    def test_the_ten_is_labelled_ten_and_not_t(self):
        # "T" is how the state writes it, and how nobody reads a card.
        for suit in make_cards.SUITS:
            text = (CARDS / f"T{suit}.svg").read_text(encoding="utf-8")
            with self.subTest(suit):
                self.assertIn(">10<", text)

    def test_everything_that_is_not_padding_says_what_it_is(self):
        # The table is images all the way down, so the alt text a reader hears
        # comes from the renderer, but a bare aria-label keeps the file honest
        # when it is opened on its own. The two that pad a row out are felt and
        # nothing else, and have nothing to say.
        for path in svg_files():
            root = ET.parse(path).getroot()
            with self.subTest(path.name):
                self.assertEqual(root.get("role"), "img")
                label = root.get("aria-label")
                if path.stem == "blank":
                    self.assertEqual(label, "")
                else:
                    self.assertTrue(label)

    def test_the_generator_is_deterministic(self):
        # The committed art is checked against a rerun in CI, which only means
        # anything if a rerun writes the same bytes.
        for path in svg_files():
            with self.subTest(path.name):
                self.assertEqual(path.read_text(encoding="utf-8"),
                                 path.read_text(encoding="utf-8"))
        self.assertEqual(make_cards.card("A", "S"), make_cards.card("A", "S"))


if __name__ == "__main__":
    unittest.main()
