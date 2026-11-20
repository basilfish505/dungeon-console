"""Shared character attribute keys used by players and monsters."""

ATTRIBUTE_KEYS = ('str', 'int', 'wis', 'chr', 'dex', 'agi', 'acc')

ATTRIBUTE_LABELS = {
    'str': 'Strength',
    'int': 'Intelligence',
    'wis': 'Wisdom',
    'chr': 'Charisma',
    'dex': 'Dexterity',
    'agi': 'Agility',
    'acc': 'Accuracy',
}


def attribute_label(key):
    return ATTRIBUTE_LABELS.get(key, str(key).upper())


def attribute_short_label(key):
    """Compact label for character-creation screens (chr -> CHA)."""
    if key == 'chr':
        return 'CHA'
    return str(key).upper()


def attrs_from_mapping(data):
    """Build an attribute dict from a mapping; missing keys default to 1."""
    if not data:
        data = {}
    out = {}
    for key in ATTRIBUTE_KEYS:
        try:
            out[key] = int(data.get(key, 1))
        except (TypeError, ValueError):
            out[key] = 1
    return out


def copy_attrs(src):
    """
    Copy ATTRIBUTE_KEYS from a mapping or object with those attributes.
    """
    if src is None:
        return attrs_from_mapping({})
    if isinstance(src, dict):
        return attrs_from_mapping(src)
    data = {}
    for key in ATTRIBUTE_KEYS:
        data[key] = getattr(src, key, 1)
    return attrs_from_mapping(data)


def gear_bonus(entity):
    """Attribute boosts from worn gear currently included in the stored stats.

    Players track this in ``applied_attribute_bonus``; a monster wearing the
    rings it will drop keeps the boosts in ``carried_loot`` (a list of entries).
    """
    raw = getattr(entity, 'applied_attribute_bonus', None)
    if not raw:
        carried = getattr(entity, 'carried_loot', None)
        entries = [carried] if isinstance(carried, dict) else (carried or [])
        raw = {}
        for entry in entries:
            boosts = entry.get('boosts') if isinstance(entry, dict) else None
            for key, amount in (boosts or {}).items():
                try:
                    raw[key] = raw.get(key, 0) + int(amount)
                except (TypeError, ValueError):
                    continue
    out = {}
    if not isinstance(raw, dict):
        return out
    for key in ATTRIBUTE_KEYS:
        try:
            amount = int(raw.get(key, 0))
        except (TypeError, ValueError):
            amount = 0
        if amount:
            out[key] = amount
    return out


def base_attributes(entity):
    """Permanent attributes only: stored stats minus worn-gear boosts.

    Use this (never ``copy_attrs`` on a player) whenever a baseline is
    captured for growth, so equipment never leaks into permanent stats.
    """
    attrs = copy_attrs(entity)
    for key, amount in gear_bonus(entity).items():
        attrs[key] = attrs[key] - amount
    return attrs


def attributes_for_inspect(entity):
    """Player-facing attribute list for inspect UI (enumerated from ATTRIBUTE_KEYS).

    ``value`` is the total used in play; ``base`` is the permanent part and
    ``bonus`` the worn-gear part, so the UI can show ``5 (+5)``.
    """
    bonus = gear_bonus(entity)
    rows = []
    for key in ATTRIBUTE_KEYS:
        value = int(getattr(entity, key, 1))
        amount = bonus.get(key, 0)
        rows.append({
            'key': key,
            'label': attribute_label(key),
            'value': value,
            'base': value - amount,
            'bonus': amount,
        })
    return rows
