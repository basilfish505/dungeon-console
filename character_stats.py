"""Shared character attribute keys used by players and monsters."""

ATTRIBUTE_KEYS = ('str', 'int', 'wis', 'chr', 'dex', 'agi')


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
