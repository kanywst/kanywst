#!/usr/bin/env python3
"""
blackjack.py

Called from GitHub Actions. Reads an issue title as one decision, plays it, and
redraws the BLACKJACK block in README.md.

Open an issue -> Action -> rewrite between the markers -> close the issue.

One table, one hand at a time, and whoever clicks next is the player. The bet is
chosen before the deal, so the shoe is worth counting: it is dealt down to a cut
card at 75% and only then shuffled, and every card that has come out of it is
listed under the table. Nothing here tells you the count. That is the game.

Every decision is priced before it is applied, from the cards actually left in
the shoe (scripts/bjmath.py), and the issue comes back with what each action was
worth and what the one you took cost. Those costs are added up per player, which
is the only scoreboard here that is not mostly variance.

A bet is answered the same way, after the fact: what the count was when the chip
went down and what the chip was worth at it. Before the fact, nothing here says
anything — the discard tray is under the table and counting it is the game.

Issue titles:
  bj|bet 2 217     - bet two units and deal hand 217
  bj|hit 217       - take a card
  bj|stand 217     - stop on this hand
  bj|double 217    - double the bet, take exactly one card
  bj|split 217     - split a pair
  bj|surrender 217 - give up half the bet
  bj|ins yes 217   - take insurance, or even money on a natural
  bj|ins no 217    - decline it

The number is the hand the link was drawn for. A link drawn before someone else
clicked is refused rather than applied to whatever is on the table now.

Environment:
  ISSUE_TITLE / ISSUE_USER / ISSUE_NUMBER

Standard output becomes the comment on the issue.
"""

import json
import os
import pathlib
import re
import secrets
from datetime import datetime, timezone

import bjmath

README_PATH = pathlib.Path("README.md")
STATE_PATH = pathlib.Path(".github/blackjack.json")
LOG_PATH = pathlib.Path(".github/blackjack-log.txt")

START_MARKER = "<!-- BLACKJACK:START -->"
END_MARKER = "<!-- BLACKJACK:END -->"

REPO = "kanywst/kanywst"
ASSET = f"https://raw.githubusercontent.com/{REPO}/main/.github/cards"
BODY = "Just+click+Submit+new+issue.+The+table+updates+in+about+30+seconds."

RULES = bjmath.VEGAS6

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K"]
SUITS = ["S", "H", "D", "C"]
SUIT_NAME = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
RANK_NAME = {"A": "ace", "T": "ten", "J": "jack", "Q": "queen", "K": "king",
             "2": "two", "3": "three", "4": "four", "5": "five", "6": "six",
             "7": "seven", "8": "eight", "9": "nine"}

CHIPS = [1, 2, 5, 10, 25]

MAX_RECENT = 3         # Hands shown under the table. The rest are in the log.
MAX_LOG_SHOES = 40     # The oldest shoes fall off first.
MAX_PLAYERS = 200
MAX_HANDS_BY = 8       # Accounts kept against one hand. Anyone can click.
NAME_ROOM = 24         # Characters of login the row has room for, past the first.
MAX_NAME = 16          # Characters of one login before the row elides it.

RNG = secrets.SystemRandom()


# --------------------------------------------------------------------------
# Cards
#
# A card is two characters, rank then suit: "TH", "AS". The calculator works in
# ten buckets and does not care which ten it is; the table does, because it has
# to draw one.
# --------------------------------------------------------------------------

def rank_of(card: str) -> str:
    return card[0]

def value_of(card: str) -> int:
    rank = rank_of(card)
    if rank == "A":
        return 1
    return 10 if rank in ("T", "J", "Q", "K") else int(rank)


def bucket_of(card: str) -> int:
    return bjmath.index_of(value_of(card))


def full_shoe(decks: int) -> list[str]:
    return [rank + suit for rank in RANKS for suit in SUITS for _ in range(decks)]


def hand_total(cards) -> int:
    values = [value_of(c) for c in cards]
    return bjmath.best_total(*bjmath.hand_state(values))


def is_soft(cards) -> bool:
    values = [value_of(c) for c in cards]
    return bjmath.is_soft(*bjmath.hand_state(values))


def is_natural(cards) -> bool:
    return len(cards) == 2 and hand_total(cards) == 21


def spell(total: int, cards) -> str:
    if total > 21:
        return f"{total} bust"
    if is_natural(cards):
        return "blackjack"
    return f"{'soft ' if is_soft(cards) else ''}{total}"


def ranks_of(cards) -> str:
    """T 6 8. Suits are left off on purpose: nothing in the game depends on
    them, and a counter reads ranks."""
    return " ".join(rank_of(c) for c in cards)


# --------------------------------------------------------------------------
# The shoe
#
# It is stored as the cards that have come out of it, in order, and nothing
# else. What is left is the difference, which means the state file cannot
# disagree with the discard tray printed under the table.
#
# The hole card is not in it. It is not drawn until the moment it is turned
# over, so there is nothing in this repository to read ahead — which is
# stricter than a real table, where the dealer has already seen it.
# --------------------------------------------------------------------------

def remaining(state: dict) -> dict[str, int]:
    left: dict[str, int] = {}
    for card in full_shoe(RULES.decks):
        left[card] = left.get(card, 0) + 1
    for card in state["shoe"]["seen"]:
        if left.get(card, 0):
            left[card] -= 1
    return left


def composition(state: dict) -> tuple[int, ...]:
    comp = [0] * 10
    for card, count in remaining(state).items():
        comp[bucket_of(card)] += count
    return tuple(comp)


def cards_left(state: dict) -> int:
    return RULES.cards - len(state["shoe"]["seen"])


def draw(state: dict, weights: tuple[float, ...] | None = None) -> str:
    """Take a card. `weights` is a distribution over the ten buckets, which is
    how the peek reaches the deal: told the dealer's ace is not covering a ten,
    a ten is that much likelier to come out next, and the calculator hands over
    the same numbers it priced the decision with."""
    left = remaining(state)
    comp = composition(state)
    if weights is None:
        total = sum(comp)
        weights = tuple(c / total for c in comp) if total else (0.0,) * 10

    roll = RNG.random()
    bucket = 9
    for i, w in enumerate(weights):
        roll -= w
        if roll <= 0:
            bucket = i
            break

    pool = [card for card, count in left.items() if count and bucket_of(card) == bucket]
    if not pool:
        pool = [card for card, count in left.items() if count]
    card = RNG.choice(sorted(pool))
    state["shoe"]["seen"].append(card)
    return card


def tilt(state: dict) -> tuple[float, ...] | None:
    """The distribution the player's next card comes from. Only a dealer who has
    peeked changes it."""
    hand = state["hand"]
    if not hand.get("peeked"):
        return None
    return bjmath.draw_probs(composition(state), value_of(hand["up"]))


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------

def blank_hand(number: int) -> dict:
    return {
        "number": number,
        "phase": "betting",
        "bet": 0,
        "insurance": 0,
        "hands": [],
        "active": 0,
        "up": None,
        "hole": None,
        "dealer": [],
        "peeked": False,
        "by": [],
    }


def blank_state() -> dict:
    return {
        "shoe": {"seen": [], "number": 1},
        "hand": blank_hand(1),
        "result": 0.0,
        "hands_played": 0,
        "coach": {"cost": 0.0, "decisions": 0},
        "players": {},
        "recent": [],
    }


def load_state() -> dict:
    """Fill whatever cannot be read with defaults, so a broken state file does
    not stop the table for good."""
    fresh = blank_state()
    if not STATE_PATH.exists():
        return fresh
    try:
        stored = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fresh
    if not isinstance(stored, dict):
        return fresh

    known = set(full_shoe(1))

    def shoe_ok(value) -> bool:
        return (isinstance(value, dict) and isinstance(value.get("seen"), list)
                and all(c in known for c in value["seen"])
                and len(value["seen"]) <= RULES.cards
                and isinstance(value.get("number"), int))

    def hand_ok(value) -> bool:
        if not isinstance(value, dict):
            return False
        if value.get("phase") not in ("betting", "insurance", "player"):
            return False
        if not isinstance(value.get("hands"), list):
            return False
        for h in value["hands"]:
            if not isinstance(h, dict) or not isinstance(h.get("cards"), list):
                return False
            if any(c not in known for c in h["cards"]):
                return False
        by = value.get("by", [])
        if not isinstance(by, list) or not all(isinstance(n, str) for n in by):
            return False
        return isinstance(value.get("number"), int) and value["number"] > 0

    checks = {
        "shoe": shoe_ok,
        "hand": hand_ok,
        "result": lambda v: isinstance(v, (int, float)),
        "hands_played": lambda v: isinstance(v, int) and v >= 0,
        "coach": lambda v: isinstance(v, dict) and {"cost", "decisions"} <= set(v),
        "players": lambda v: isinstance(v, dict),
        "recent": lambda v: isinstance(v, list),
    }
    for key, ok in checks.items():
        if key in stored:
            try:
                if ok(stored[key]):
                    fresh[key] = stored[key]
            except (TypeError, AttributeError, ValueError):
                pass
    return fresh


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".json.tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_PATH)


# --------------------------------------------------------------------------
# Playing a hand
# --------------------------------------------------------------------------

def active(state: dict) -> dict:
    return state["hand"]["hands"][state["hand"]["active"]]


def options(state: dict) -> dict:
    """Which actions the hand in play may take, and why not where it may not."""
    hand = state["hand"]
    if hand["phase"] != "player":
        return {}
    spot = active(state)
    two = len(spot["cards"]) == 2
    pair = two and value_of(spot["cards"][0]) == value_of(spot["cards"][1])
    from_split = bool(spot.get("from_split"))
    split_ace = from_split and value_of(spot["cards"][0]) == 1
    can_hit = not (split_ace and not RULES.hit_split_aces)
    return {
        "hit": can_hit,
        "stand": True,
        "double": two and can_hit and (not from_split or RULES.double_after_split),
        "split": (pair and len(hand["hands"]) <= RULES.max_splits
                  and (not split_ace or RULES.resplit_aces)),
        "surrender": two and not from_split and RULES.late_surrender,
    }


def coach(state: dict, action: str) -> tuple[str, float]:
    """What every action was worth, and what this one cost.

    Priced before the card comes out, from the shoe as it stands, with the hole
    card still in it — because nobody has seen it, so as far as this hand is
    concerned it is still in the shoe.
    """
    hand = state["hand"]
    spot = active(state)
    allowed = options(state)
    values = [value_of(c) for c in spot["cards"]]
    ev = bjmath.action_evs(
        composition(state), values, value_of(hand["up"]), RULES,
        can_double=allowed["double"], can_split=allowed["split"],
        can_surrender=allowed["surrender"],
        splits_left=RULES.max_splits - len(hand["hands"]),
    )
    priced = ev.options()
    if action not in priced:
        return "", 0.0
    best = max(priced.items(), key=lambda kv: kv[1])
    cost = priced[action] - best[1]

    # Fenced, because the comment this ends up in is markdown and two spaces
    # of indent are not a code block: the rows would run into one paragraph and
    # the numbers would stop lining up.
    lines = ["```text"]
    for name, value in sorted(priced.items(), key=lambda kv: -kv[1]):
        mark = "  best" if name == best[0] else ("  <- you" if name == action else "")
        lines.append(f"{name.title():<10}{value:+.4f}{mark}")
    lines.append("```")
    return "\n".join(lines), cost


def handle(user: str) -> str:
    """A GitHub login, or nothing at all.

    The name goes onto the profile page as a link, so only what a login can
    actually be gets written there: letters, digits and single hyphens, 39
    characters at most. Anything else is a name the table declines to print,
    including whatever a hand-edited state file might be holding instead of a
    string.
    """
    if not isinstance(user, str) or len(user) > 39:
        return ""
    if re.fullmatch(r"[A-Za-z0-9](?:-?[A-Za-z0-9])*", user):
        return user
    return ""


def touch(state: dict, user: str) -> None:
    """Note that this account played the hand on the table.

    The table is a queue of strangers, so a hand is not necessarily one
    person's: whoever bets it may not be whoever hits it. Kept in the order
    they arrived, first come first named.
    """
    name = handle(user)
    by = state["hand"].setdefault("by", [])
    if name and name not in by and len(by) < MAX_HANDS_BY:
        by.append(name)


def player(state: dict, user: str) -> dict:
    """The record kept for one player, made if it is not there.

    Every path that can add a name goes through here, including the hands that
    settle without anyone taking a decision — a natural, or a dealer who peeked
    and had one. Otherwise the ceiling below would only be applied on the paths
    that happen to reach it, and a public state file would grow past it.
    """
    touch(state, user)
    who = state["players"].setdefault(user, {"hands": 0, "decisions": 0, "cost": 0.0})
    if len(state["players"]) > MAX_PLAYERS:
        # Only the count is ever shown, and a table played by the whole internet
        # should not grow a state file without end. The player in front of the
        # table is never the one dropped.
        ranked = sorted(((name, stat) for name, stat in state["players"].items()
                         if name != user), key=lambda kv: -kv[1]["decisions"])
        state["players"] = dict(ranked[:MAX_PLAYERS - 1] + [(user, who)])
    return who


def record_decision(state: dict, user: str, cost: float) -> None:
    state["coach"]["cost"] += cost
    state["coach"]["decisions"] += 1
    who = player(state, user)
    who["decisions"] += 1
    who["cost"] += cost


def count_note(state: dict, bet: float) -> str:
    """What the chip was worth before a card came out.

    The table never volunteers the count while there is still a bet to make —
    the cards that have come out are printed under it and counting them is the
    game. This is the answer afterwards, which is how a counting drill works:
    bet first, then find out what the shoe was.
    """
    seen = [value_of(c) for c in state["shoe"]["seen"]]
    running = bjmath.hi_lo(seen)
    left = cards_left(state)
    tc = bjmath.true_count(running, left)
    edge = bjmath.edge_at(tc)
    return (f"When that chip went down the running count was {running:+d} with"
            f" {left / 52:.1f} decks left, so the true count was {tc:+.1f}."
            f" A shoe like that is worth about {edge * 100:+.2f}% a unit, measured"
            f" over 200 million rounds of these rules — so {money(bet)} on it was"
            f" worth {edge * bet:+.3f} units before a card came out.")


def deal(state: dict, bet: float, user: str) -> str:
    hand = state["hand"]
    hand["bet"] = bet
    hand["hands"] = [{"cards": [], "bet": bet, "doubled": False, "done": False,
                      "surrendered": False, "from_split": False}]
    hand["active"] = 0
    hand["dealer"] = []
    hand["hole"] = None
    hand["peeked"] = False

    spot = hand["hands"][0]
    spot["cards"].append(draw(state))
    hand["up"] = draw(state)
    spot["cards"].append(draw(state))

    player(state, user)["hands"] += 1

    up = value_of(hand["up"])
    if up == 1:
        # Insurance is offered before the dealer looks, which is the only reason
        # it is a bet at all.
        hand["phase"] = "insurance"
        return (f"Hand {hand['number']} for {money(bet)}. The dealer shows an ace"
                f" and you have {spell(hand_total(spot['cards']), spot['cards'])}."
                " Insurance?")

    if up == 10:
        peek(state)
        if hand["hole"]:
            return settle(state, "The dealer had blackjack.")

    hand["phase"] = "player"
    if is_natural(spot["cards"]):
        return settle(state, "Blackjack.")
    return f"Hand {hand['number']} for {money(bet)}."


def peek(state: dict) -> bool:
    """The dealer looks. Only one bit of the answer exists until this moment:
    the hole card itself is not drawn unless it ends the hand, and otherwise
    stays undrawn until it is turned over."""
    hand = state["hand"]
    hand["peeked"] = True
    up = value_of(hand["up"])
    partner = bjmath.TEN if up == 1 else bjmath.ACE
    comp = composition(state)
    total = sum(comp)
    if total and RNG.random() < comp[partner] / total:
        weights = tuple(1.0 if i == partner else 0.0 for i in range(10))
        hand["hole"] = draw(state, weights)
        return True
    return False


def reveal(state: dict) -> None:
    """Turn the hole card over. It is drawn now, from what the peek left
    possible — the same distribution the calculator has been assuming all
    along."""
    hand = state["hand"]
    if hand["hole"]:
        return
    weights = None
    if hand["peeked"]:
        weights = bjmath.hole_weights(composition(state), value_of(hand["up"]))
    hand["hole"] = draw(state, weights)


def dealer_cards(state: dict) -> list[str]:
    hand = state["hand"]
    cards = [hand["up"]]
    if hand["hole"]:
        cards.append(hand["hole"])
    return cards + hand["dealer"]


def play_dealer(state: dict) -> None:
    hand = state["hand"]
    reveal(state)
    while True:
        cards = dealer_cards(state)
        total = hand_total(cards)
        if total > 21 or total > 17:
            return
        if total == 17 and not (RULES.hit_soft_17 and is_soft(cards)):
            return
        hand["dealer"].append(draw(state))


def advance(state: dict) -> str:
    """Move to the next hand that still has a decision, or let the dealer play."""
    hand = state["hand"]
    for i, spot in enumerate(hand["hands"]):
        if not spot["done"]:
            hand["active"] = i
            # A split hand that has just been dealt its second card may still
            # need one; a split ace that may not be hit is finished on arrival.
            if len(spot["cards"]) == 1:
                spot["cards"].append(draw(state, tilt(state)))
            if (spot.get("from_split") and value_of(spot["cards"][0]) == 1
                    and not RULES.hit_split_aces):
                spot["done"] = True
                continue
            if hand_total(spot["cards"]) >= 21:
                spot["done"] = True
                continue
            hand["phase"] = "player"
            return ""
    return settle(state, "")


def settle(state: dict, note: str) -> str:
    hand = state["hand"]
    # The dealer only draws where drawing can change something. A hand that is
    # gone, busted, or a natural the dealer can no longer match is not a reason
    # to burn cards out of a shoe people are counting.
    playable = [s for s in hand["hands"]
                if not s["surrendered"] and hand_total(s["cards"]) <= 21
                and not (is_natural(s["cards"]) and not s["from_split"])]
    if playable:
        play_dealer(state)
    else:
        reveal(state)

    dealer = dealer_cards(state)
    dealer_total = hand_total(dealer)
    dealer_natural = is_natural(dealer)

    net = 0.0
    for spot in hand["hands"]:
        total = hand_total(spot["cards"])
        if spot["surrendered"]:
            spot["result"] = "surrendered"
            net -= spot["bet"] / 2
        elif is_natural(spot["cards"]) and not spot["from_split"]:
            if dealer_natural:
                spot["result"] = "push"
            else:
                spot["result"] = "blackjack"
                net += spot["bet"] * RULES.blackjack_pays
        elif total > 21:
            spot["result"] = "bust"
            net -= spot["bet"]
        elif dealer_natural or (dealer_total <= 21 and dealer_total > total):
            spot["result"] = "lost"
            net -= spot["bet"]
        elif dealer_total > 21 or total > dealer_total:
            spot["result"] = "won"
            net += spot["bet"]
        else:
            spot["result"] = "push"

    if hand["insurance"]:
        net += hand["insurance"] * 2 if dealer_natural else -hand["insurance"]

    state["result"] += net
    state["hands_played"] += 1
    remember(state, net, dealer, dealer_total)
    append_log(state, net, dealer)

    number = hand["number"]
    state["hand"] = blank_hand(number + 1)
    reshuffle(state)

    parts = [note] if note else []
    parts.append(describe_result(state["recent"][0]))
    played = state["hands_played"]
    parts.append(f"The table is {money(state['result'], signed=True)} over"
                 f" {played} hand{'' if played == 1 else 's'}.")
    return " ".join(p for p in parts if p)


def remember(state: dict, net: float, dealer: list[str], dealer_total: int) -> None:
    hand = state["hand"]
    entry = {
        "number": hand["number"],
        "bet": hand["bet"],
        "hands": [{"cards": list(s["cards"]), "result": s["result"],
                    "bet": s["bet"], "doubled": s["doubled"]} for s in hand["hands"]],
        "dealer": list(dealer),
        "dealer_total": dealer_total,
        "insurance": hand["insurance"],
        "net": net,
        "by": list(hand.get("by", [])),
    }
    state["recent"].insert(0, entry)
    del state["recent"][MAX_RECENT:]


def elide(name: str) -> str:
    """A login the width of a column can live with.

    A cell that has to hold 39 characters takes the width from every other
    column beside it, and on a phone that is the whole table. The link still
    goes to the account, and the full name is on the link itself.
    """
    return name if len(name) <= MAX_NAME else name[:MAX_NAME - 1] + "…"


def fitting(names: list[str]) -> tuple[list[str], int]:
    """As many logins as one line has room for, and how many are left over.

    Measured in characters rather than in names because a login can be 39 of
    them, and the line they go on — a table row, a sentence — is not this
    table's page. First come, first named.
    """
    shown, room = [], NAME_ROOM
    for name in names:
        if shown and len(name) + 1 > room:
            break
        room -= len(name) + 1
        shown.append(name)
    return shown, len(names) - len(shown)


def names_of(entry: dict) -> str:
    """The accounts that played a settled hand, as a sentence says them.

    Plain text rather than links: the same sentence is posted back as the
    comment on the issue that played the hand, where a bare @name is already
    the account.
    """
    names = [n for n in entry.get("by", []) if handle(n)]
    if not names:
        return ""
    shown, rest = fitting(names)
    parts = [f"@{n}" for n in shown]
    if rest:
        parts.append(f"{rest} other{'' if rest == 1 else 's'}")
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def describe_result(entry: dict) -> str:
    """One sentence for a hand that is over.

    In the order the cards are on the felt, dealer first, and in the past tense,
    because the hand it describes has been settled. Said in the present it reads
    like a hand still waiting on a decision, and two totals with no winner named
    is not a result.
    """
    dealer_total = entry["dealer_total"]
    dealer_text = ("busted with " + str(dealer_total) if dealer_total > 21
                   else ("had blackjack" if is_natural(entry["dealer"])
                         else f"had {dealer_total}"))

    doubled = any(s.get("doubled") for s in entry["hands"])
    totals = " and ".join(spell(hand_total(s["cards"]), s["cards"]) for s in entry["hands"])

    net = entry["net"]
    if net > 0:
        money_text = f"it paid {money(net)}"
    elif net < 0:
        money_text = f"it cost {money(-net)}"
    else:
        money_text = "it ended level"

    # The hand is over, so the person who played it is a name, not a "you":
    # the sentence sits on a profile page that anybody reads. A hand with no
    # name on it — one played before the table kept them — keeps the pronoun.
    who = names_of(entry)
    if entry["hands"][0]["result"] == "surrendered":
        mine = f"{who} gave up {totals}" if who else f"you gave up {totals}"
    elif doubled:
        # Naming the double is what explains a hand that cost twice its chip.
        mine = (f"{who}'s double came to {totals}" if who
                else f"your double came to {totals}")
    else:
        mine = f"{who} had {totals}" if who else f"you had {totals}"
    return f"Hand {entry['number']}: the dealer {dealer_text}, {mine}, and {money_text}."


def reshuffle(state: dict) -> None:
    """The cut card. A shoe is only shuffled between hands, which is what makes
    counting it worth anything."""
    if len(state["shoe"]["seen"]) < round(RULES.cards * RULES.penetration):
        return
    log_shoe(state)
    state["shoe"] = {"seen": [], "number": state["shoe"]["number"] + 1}


def money(amount: float, signed: bool = False) -> str:
    sign = "+" if signed and amount > 0 else ("-" if amount < 0 else "")
    value = abs(amount)
    body = f"{value:,.1f}".rstrip("0").rstrip(".")
    return f"{sign}{body}u"


# --------------------------------------------------------------------------
# The log
# --------------------------------------------------------------------------

def append_log(state: dict, net: float, dealer: list[str]) -> None:
    hand = state["hand"]
    hands = " / ".join(
        f"{ranks_of(s['cards'])} {hand_total(s['cards'])} {s['result']}"
        for s in hand["hands"]
    )
    line = (f"  {hand['number']:>5}  {money(hand['bet']):>5}  {hands}"
            f"  |  dealer {ranks_of(dealer)} {hand_total(dealer)}"
            f"  |  {money(net, signed=True)}")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else header()
    LOG_PATH.write_text(existing.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")


def header() -> str:
    return ("Blackjack played on github.com/kanywst. Newest last.\n"
            "Hand, bet, the player's cards, the dealer's, and what the table won.\n")


def log_shoe(state: dict) -> None:
    """Close the shoe with every card it dealt, in order, so the count anyone
    was keeping can be checked afterwards."""
    seen = state["shoe"]["seen"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ranks = " ".join(rank_of(c) for c in seen)
    body = "\n".join("    " + ranks[i:i + 96] for i in range(0, len(ranks), 96))
    entry = (f"\n  shoe {state['shoe']['number']} closed {stamp}, {len(seen)} cards\n"
             f"{body}\n\n")
    existing = LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else header()
    text = existing.rstrip("\n") + "\n" + entry
    # Keep the file from growing without end: the oldest shoes go first.
    shoes = text.split("\n  shoe ")
    if len(shoes) > MAX_LOG_SHOES + 1:
        text = header() + "\n  shoe " + "\n  shoe ".join(shoes[-MAX_LOG_SHOES:])
    LOG_PATH.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------
# Drawing the table
#
# The same constraints the shogi board was drawn under, for the same reasons.
# Images inside a pre, because GitHub pads and borders every cell of a table and
# a row of cards would read as a spreadsheet. No width or height on the img,
# because a sized image is given a 6px border radius and a background of
# GitHub's choosing, which turns a table into a row of rounded tiles. Every
# image inside a link of our own, because without one GitHub wraps it in a link
# to the raw SVG.
# --------------------------------------------------------------------------

def issue_url(command: str) -> str:
    quoted = command.replace(" ", "+")
    return f"https://github.com/{REPO}/issues/new?title=bj%7C{quoted}&body={BODY}"


def img(name: str, alt: str) -> str:
    return f'<img src="{ASSET}/{name}.svg" align="top" alt="{alt}">'


def linked(inner: str, href: str) -> str:
    return f'<a href="{href}">{inner}</a>'


def here() -> str:
    return f"https://github.com/{REPO}#blackjack"


def card_img(card: str, alt: str | None = None) -> str:
    return img(card, alt if alt is not None else
               f"{RANK_NAME[rank_of(card)]} of {SUIT_NAME[card[1]]}")


def strip(images: list[str]) -> str:
    return '<div align="center"><pre>' + "".join(images) + "</pre></div>"


def felt(rows: list[str]) -> str:
    """The table: every row on its own line inside one pre."""
    return '<div align="center"><pre>' + "\n".join(rows) + "</pre></div>"


def centre(text: str) -> str:
    return f'<p align="center">{text}</p>'


def sign() -> str:
    return centre(
        f"{RULES.decks} decks · dealer stands on soft 17 · double after split"
        f" · late surrender · blackjack pays 3 to 2 · shuffled at the"
        f" {round(RULES.penetration * 100)}% cut card"
    )


def how() -> str:
    """The only instruction on the table, and the only one it needs: what the
    game is, what a click does, and how long to wait for it."""
    return centre(
        "Beat the dealer without going over 21. A click opens a prefilled issue:"
        " submit it and the table moves in about 30 seconds."
    )


def felt_row(images: list[str], width: int) -> str:
    """One row of the table, padded out to the width of the longest one.

    The rows go inside one pre rather than one each. GitHub gives a pre a
    background of its own, so a pre per row bands the table in grey and the
    felt stops being one surface — the same reason the shogi board was one pre
    of nine ranks.
    """
    padded = images + [img("blank", "")] * (width + 1 - len(images))
    return "".join(linked(image, here()) for image in padded)


def table_width(state: dict, entry: dict | None = None) -> int:
    hands = entry["hands"] if entry else state["hand"]["hands"]
    dealer = len(entry["dealer"]) if entry else max(len(dealer_cards(state)), 2)
    return max([dealer, 2] + [len(h["cards"]) for h in hands])


def dealer_row(state: dict, width: int, revealed: bool) -> str:
    hand = state["hand"]
    images = [img("label-dealer", "dealer")]
    if not hand["up"]:
        images += [img("slot", "empty slot"), img("slot", "empty slot")]
    elif revealed:
        images += [card_img(c) for c in dealer_cards(state)]
    else:
        images += [card_img(hand["up"]),
                   img("back", "the dealer's hole card, face down")]
    return felt_row(images, width)


def hand_rows(state: dict, width: int) -> list[str]:
    hand = state["hand"]
    live = hand["phase"] == "player"
    if not hand["hands"]:
        return [felt_row([img("label-you", "you"), img("slot", "empty slot"),
                          img("slot", "empty slot")], width)]
    rows = []
    # The frame says which of several hands is in play. With one hand there is
    # nothing to tell apart, and a frame around it only reads as an alarm.
    split = len(hand["hands"]) > 1
    for i, spot in enumerate(hand["hands"]):
        turn = live and split and i == hand["active"]
        images = [img("label-you-sel", "your hand, in play") if turn
                  else img("label-you", "you")]
        images += [card_img(c) for c in spot["cards"]]
        rows.append(felt_row(images, width))
    return rows


def buttons(state: dict) -> str:
    hand = state["hand"]
    number = hand["number"]
    if hand["phase"] == "insurance":
        offered = [("insure", f"ins yes {number}"), ("no", f"ins no {number}")]
    elif hand["phase"] == "player":
        allowed = options(state)
        offered = [(name, f"{name} {number}")
                   for name in ("hit", "stand", "double", "split", "surrender")
                   if allowed.get(name)]
    else:
        offered = []
    if not offered:
        return ""
    return strip([linked(img(f"btn-{name}", name), issue_url(command))
                  for name, command in offered])


def chips(state: dict) -> str:
    number = state["hand"]["number"]
    return strip([
        linked(img(f"chip{value}", f"bet {value} unit{'' if value == 1 else 's'}"),
               issue_url(f"bet {value} {number}"))
        for value in CHIPS
    ])


def headline(state: dict) -> str:
    hand = state["hand"]
    # The dealer is named first throughout, because the dealer's cards are the
    # top row. A sentence in the other order asks the reader to work out which
    # row is theirs.
    if hand["phase"] == "insurance":
        return ("The dealer shows an ace and has not looked yet."
                " Insurance costs half your bet and pays 2 to 1.")
    if hand["phase"] == "player":
        spot = active(state)
        mine = spell(hand_total(spot["cards"]), spot["cards"])
        where = "" if len(hand["hands"]) == 1 else f" on hand {hand['active'] + 1}"
        return (f"The dealer shows {RANK_NAME[rank_of(hand['up'])]},"
                f" and you have {mine}{where}.")
    # Between hands the table has to say what to click next. It is the one
    # moment where the thing to press is not obviously a button.
    deal = f"Pick a chip to deal hand {hand['number']}."
    if state["recent"]:
        return f"{describe_result(state['recent'][0])} {deal}"
    return deal


def shoe_line(state: dict) -> str:
    left = cards_left(state)
    decks = left / 52
    seen = state["shoe"]["seen"]
    shown = 24
    tray = " ".join(rank_of(c) for c in seen[-shown:])
    if not seen:
        return centre(f"Shoe {state['shoe']['number']} · freshly shuffled"
                      f" · {decks:.1f} decks left")
    where = f"https://github.com/{REPO}/blob/main/.github/blackjack.json"
    rest = (f' · <a href="{where}">all {len(seen)}</a>' if len(seen) > shown else "")
    return centre(f"Shoe {state['shoe']['number']} · {decks:.1f} decks left"
                  f" · out of it: {tray}{rest}")


def stats_line(state: dict) -> str:
    coach_cost = state["coach"]["cost"]
    parts = [
        f"{money(state['result'], signed=True)} over"
        f" {state['hands_played']} hand{'' if state['hands_played'] == 1 else 's'}",
        f"{len(state['players'])} player{'' if len(state['players']) == 1 else 's'}",
    ]
    if state["coach"]["decisions"]:
        parts.append(f"{money(abs(coach_cost))} lost to mistakes")
    return centre(" · ".join(parts))


def played_by(entry: dict) -> str:
    """Who took the hand, linked to the account that took it.

    A row that says "you" to everyone who reads the profile names nobody: the
    person at the table was one particular account, and the visitor reading it
    is usually not them. The rest are counted rather than named, because a
    column that grows with the queue stops being a column — and a login can be
    39 characters, so what fits is measured in characters and not in names.
    """
    names = [n for n in entry.get("by", []) if handle(n)]
    if not names:
        return ""
    fits, rest = fitting([elide(n) for n in names])
    shown = [f'<a href="https://github.com/{n}" title="@{n}">@{text}</a>'
             for n, text in zip(names, fits)]
    if rest:
        shown.append(f"+{rest}")
    return " ".join(shown)


def recent_table(state: dict) -> list[str]:
    if not state["recent"]:
        return []
    rows = []
    for entry in state["recent"]:
        mine = " / ".join(
            f"{spell(hand_total(s['cards']), s['cards'])} ({ranks_of(s['cards'])})"
            for s in entry["hands"]
        )
        dealer = entry["dealer"]
        total = entry["dealer_total"]
        shown = ("blackjack" if is_natural(dealer) else
                 (f"{total} bust" if total > 21 else str(total)))
        who = played_by(entry)
        rows.append(
            f"    <tr><td><code>{entry['number']}</code>{' ' + who if who else ''}</td>"
            f"<td>{mine}</td>"
            f"<td>{shown} ({ranks_of(dealer)})</td>"
            f"<td><code>{money(entry['net'], signed=True)}</code></td></tr>"
        )
    return [
        '<table align="center">',
        "  <thead>",
        "    <tr><th>Hand</th><th>Player</th><th>Dealer</th><th></th></tr>",
        "  </thead>",
        "  <tbody>",
        *rows,
        "  </tbody>",
        "</table>",
    ]


def render(state: dict) -> str:
    hand = state["hand"]
    betting = hand["phase"] == "betting"
    lines = []

    if betting and state["recent"]:
        # The hand that just ended stays on the felt, face up, until the next
        # chip goes out. A table that empties itself the moment it is settled
        # never shows anyone what happened.
        lines += [replay(state), ""]
    else:
        width = table_width(state)
        lines += [felt([dealer_row(state, width, revealed=False)]
                       + hand_rows(state, width)), ""]

    head = headline(state)
    if head:
        lines += [centre(head), ""]
    action = chips(state) if betting else buttons(state)
    if action:
        lines += [action, ""]

    lines += [how(), "", shoe_line(state), "", stats_line(state), ""]
    lines += recent_table(state)
    lines += ["" if state["recent"] else None, sign()]
    return "\n".join(line for line in lines if line is not None)


def replay(state: dict) -> str:
    """The last finished hand, dealer's cards and all."""
    entry = state["recent"][0]
    width = table_width(state, entry)
    rows = [felt_row([img("label-dealer", "dealer")]
                     + [card_img(c) for c in entry["dealer"]], width)]
    for spot in entry["hands"]:
        rows.append(felt_row([img("label-player", "player")]
                             + [card_img(c) for c in spot["cards"]], width))
    return felt(rows)


def write_readme(state: dict) -> None:
    content = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}", re.DOTALL
    )
    if not pattern.search(content):
        raise SystemExit("BLACKJACK markers not found in README.md")
    block = f"{START_MARKER}\n{render(state)}\n{END_MARKER}"
    README_PATH.write_text(pattern.sub(lambda _: block, content), encoding="utf-8")


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def play(state: dict, command: str, user: str) -> str:
    parts = command.split()
    verb = parts[0]
    hand = state["hand"]

    number = int(parts[-1])
    if number != hand["number"]:
        return (f"That link was drawn for hand {number} and the table is on"
                f" {hand['number']}. Someone got there first — click again.")

    if verb == "bet":
        if hand["phase"] != "betting":
            return "There is a hand on the table. Play it out first."
        amount = float(parts[1])
        if amount not in CHIPS:
            return "That is not one of the chips."
        note = count_note(state, amount)
        return f"{deal(state, amount, user)}\n\n{note}"

    if hand["phase"] == "betting":
        return "Nothing has been dealt. Put a chip out first."

    if verb == "ins":
        if hand["phase"] != "insurance":
            return "Nobody is being offered insurance."
        taking = parts[1] == "yes"
        spot = hand["hands"][0]
        # Insurance is a bet on the hole card and nothing else, so it is priced
        # against the shoe rather than against the hand.
        comp = composition(state)
        chance = comp[bjmath.TEN] / sum(comp)
        take_ev = (chance * 2 - (1 - chance)) * 0.5
        record_decision(state, user, (take_ev if taking else 0.0) - max(take_ev, 0.0))

        if taking:
            hand["insurance"] = hand["bet"] / 2
        natural = peek(state)
        note = (f"Insurance pays 2:1 and the hole card is a ten"
                f" {chance * 100:.1f}% of the time here, so it is worth"
                f" {take_ev:+.4f} a unit. It needs 33.3% to break even.")
        if natural:
            return settle(state, f"The dealer had blackjack. {note}")
        hand["phase"] = "player"
        if is_natural(spot["cards"]):
            return settle(state, f"Blackjack. {note}")
        return f"No blackjack. {note} Your move."

    if hand["phase"] != "player":
        return "Answer the insurance question first."

    allowed = options(state)
    if verb not in allowed:
        return f"Cannot read '{command}' as a move."
    if not allowed[verb]:
        return f"You cannot {verb} that hand."

    table, cost = coach(state, verb)
    record_decision(state, user, cost)
    spot = active(state)

    if verb == "surrender":
        spot["surrendered"] = True
        spot["done"] = True
        return finish(state, table, cost, "You give up half the bet.")

    if verb == "stand":
        spot["done"] = True
        return finish(state, table, cost, f"You stand on {hand_total(spot['cards'])}.")

    if verb == "double":
        spot["bet"] *= 2
        spot["doubled"] = True
        spot["cards"].append(draw(state, tilt(state)))
        spot["done"] = True
        total = hand_total(spot["cards"])
        note = (f"You double to {money(spot['bet'])}, draw {name_of(spot['cards'][-1])}"
                f" and have {spell(total, spot['cards'])}.")
        return finish(state, table, cost, note)

    if verb == "hit":
        spot["cards"].append(draw(state, tilt(state)))
        total = hand_total(spot["cards"])
        note = (f"You draw {name_of(spot['cards'][-1])} for"
                f" {spell(total, spot['cards'])}.")
        if total >= 21:
            spot["done"] = True
        return finish(state, table, cost, note)

    if verb == "split":
        moved = spot["cards"].pop()
        spot["from_split"] = True
        new = {"cards": [moved], "bet": hand["bet"], "doubled": False, "done": False,
               "surrendered": False, "from_split": True}
        hand["hands"].insert(hand["active"] + 1, new)
        spot["cards"].append(draw(state, tilt(state)))
        note = f"You split them, and the first hand draws {name_of(spot['cards'][-1])}."
        if hand_total(spot["cards"]) >= 21 or (value_of(spot["cards"][0]) == 1
                                               and not RULES.hit_split_aces):
            spot["done"] = True
        return finish(state, table, cost, note)

    return f"Cannot read '{command}' as a move."


def finish(state: dict, table: str, cost: float, note: str) -> str:
    """Whatever the decision was, followed by what it was worth."""
    tail = advance(state)
    lines = [note]
    if tail:
        lines.append(tail)
    if table:
        lines.append("")
        lines.append(table)
        lines.append("")
        if cost < -0.0001:
            lines.append(f"That cost {abs(cost):.4f} units, priced against the"
                         f" {cards_left(state)} cards still in the shoe.")
        else:
            lines.append(f"Best available, priced against the {cards_left(state)}"
                         " cards still in the shoe.")
    return "\n".join(lines)


def name_of(card: str) -> str:
    return f"the {RANK_NAME[rank_of(card)]} of {SUIT_NAME[card[1]]}"


def parse(title: str) -> str | None:
    match = re.search(
        r"bj\s*\|\s*("
        r"bet\s+(?:1|2|5|10|25)\s+\d{1,6}"
        r"|(?:hit|stand|double|split|surrender)\s+\d{1,6}"
        r"|ins\s+(?:yes|no)\s+\d{1,6}"
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
        print("That is not a move I can read. Click a button on the table instead.")
        return

    state = load_state()
    message = play(state, command, user)
    # The state file first: it is what the next click plays against, and the
    # table is drawn from it. Written the other way round, a run that dies in
    # between would leave a profile showing a hand that was never recorded.
    save_state(state)
    write_readme(state)
    print(message)


if __name__ == "__main__":
    main()
