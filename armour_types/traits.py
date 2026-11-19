"""Parse the armour sheet's ``other_ability`` cell into special traits.

Currently the only trait is an attribute boost. Each entry is
``<attribute>: <amount>`` or ``<attribute>: <low>-<high>``; several entries
are separated by ``;`` or ``,``. A range is rolled once when an item is
created (so every ring of the same type can differ) and then stays fixed.

Examples: ``str: 1-5``   ``dex +2``   ``acc: 3..6; agi: 1``
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from character_stats import ATTRIBUTE_KEYS

# Accepted spellings besides the short keys (str, int, ...).
_ATTRIBUTE_ALIASES = {
    'strength': 'str',
    'intelligence': 'int',
    'wisdom': 'wis',
    'charisma': 'chr',
    'cha': 'chr',
    'dexterity': 'dex',
    'agility': 'agi',
    'accuracy': 'acc',
}

_ENTRY_RE = re.compile(
    r'^(?P<attr>[A-Za-z_]+)\s*[:=]?\s*\+?\s*'
    r'(?P<low>-?\d+)'
    r'(?:\s*(?:-|\.\.|to)\s*\+?(?P<high>-?\d+))?$',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AttributeBoost:
    attribute: str
    low: int
    high: int

    @property
    def is_fixed(self):
        return self.low == self.high

    def to_dict(self):
        return {'attribute': self.attribute, 'low': self.low, 'high': self.high}


def normalize_attribute(name):
    """Map a sheet spelling to an ATTRIBUTE_KEYS key, or None."""
    key = str(name or '').strip().lower()
    if key in ATTRIBUTE_KEYS:
        return key
    return _ATTRIBUTE_ALIASES.get(key)


def parse_other_ability(text):
    """Return ``(boosts, unrecognised)`` for an ``other_ability`` cell.

    Entries that are not understood are returned (not raised) so a typo in
    the spreadsheet never stops the game from loading.
    """
    boosts = []
    unrecognised = []
    if text is None:
        return boosts, unrecognised
    for raw in re.split(r'[;,\n]', str(text)):
        entry = raw.strip()
        if not entry:
            continue
        match = _ENTRY_RE.match(entry)
        attribute = normalize_attribute(match.group('attr')) if match else None
        if match is None or attribute is None:
            unrecognised.append(entry)
            continue
        low = int(match.group('low'))
        high = int(match.group('high')) if match.group('high') is not None else low
        if low > high:
            low, high = high, low
        boosts.append(AttributeBoost(attribute, low, high))
    return boosts, unrecognised


def roll_boosts(boosts, rng=None):
    """Roll each boost once -> ``{attribute: amount}`` (zero amounts omitted)."""
    source = rng if rng is not None else random
    rolled = {}
    for boost in boosts or ():
        amount = source.randint(boost.low, boost.high)
        if amount:
            rolled[boost.attribute] = rolled.get(boost.attribute, 0) + amount
    return rolled


def clean_rolled_boosts(raw):
    """Sanitise a saved ``{attribute: amount}`` mapping."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        attribute = normalize_attribute(key)
        if attribute is None:
            continue
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        if amount:
            out[attribute] = out.get(attribute, 0) + amount
    return out
