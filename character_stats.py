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


def attributes_for_inspect(entity):
    """Player-facing attribute list for inspect UI (enumerated from ATTRIBUTE_KEYS)."""
    rows = []
    for key in ATTRIBUTE_KEYS:
        rows.append({
            'key': key,
            'label': attribute_label(key),
            'value': int(getattr(entity, key, 1)),
        })
    return rows
