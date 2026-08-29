"""Spell type definition — static library data shared by all casters."""

from character_stats import ATTRIBUTE_KEYS, ATTRIBUTE_LABELS

# Known effect / targeting / hit-rule ids. Unknown values still load so a
# sheet typo cannot crash combat; cast-time validation rejects them instead.
EFFECT_TYPES = frozenset({
    'damage', 'heal', 'buff', 'debuff', 'status', 'utility',
})
TARGET_MODES = frozenset({
    'single_enemy', 'self', 'single_ally', 'single_any',
    'all_enemies', 'all_allies',
})
HIT_RULES = frozenset({'always_hit', 'accuracy'})

_LABEL_TO_ATTR = {
    label.lower(): key for key, label in ATTRIBUTE_LABELS.items()
}

_TRUTHY = frozenset({'1', 'true', 'yes', 'y', 'on'})
_FALSY = frozenset({'0', 'false', 'no', 'n', 'off'})


def _canon(value):
    """Lowercase and turn spaces/hyphens into underscores."""
    if value is None:
        return ''
    text = str(value).strip().lower()
    text = text.replace('-', '_').replace(' ', '_')
    while '__' in text:
        text = text.replace('__', '_')
    return text


def _resolve_scaling_attribute(value, default='int'):
    """Accept 'int' or 'Intelligence' (any ATTRIBUTE_LABELS name)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    raw = str(value).strip()
    key = _canon(raw)
    if key in ATTRIBUTE_KEYS:
        return key
    by_label = _LABEL_TO_ATTR.get(raw.lower())
    if by_label is not None:
        return by_label
    by_canon_label = _LABEL_TO_ATTR.get(key.replace('_', ' '))
    if by_canon_label is not None:
        return by_canon_label
    return default


def _parse_bool(value, default=True):
    if value is None or (isinstance(value, str) and not value.strip()):
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    key = str(value).strip().lower()
    if key in _TRUTHY:
        return True
    if key in _FALSY:
        return False
    return bool(default)


def _optional_int(value):
    """Return int or None when blank."""
    if value is None or (isinstance(value, str) and not str(value).strip()):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class SpellTypeDef:
    """Reusable spell definition identified by stable spell_id."""

    def __init__(
        self,
        spell_id,
        name=None,
        description=None,
        effect_type='damage',
        target_mode='single_enemy',
        mp_cost=0,
        base_power=0,
        scaling_attribute='int',
        scaling_factor=1.0,
        hit_rule='always_hit',
        spell_range=1,
        min_power=None,
        max_power=None,
        usable_in_combat=True,
        usable_out_of_combat=False,
    ):
        self.id = str(spell_id).strip()
        self.name = str(name).strip() if name else self.id
        self.description = description if description else None

        self.effect_type = _canon(effect_type) or 'damage'
        self.target_mode = _canon(target_mode) or 'single_enemy'
        self.hit_rule = _canon(hit_rule) or 'always_hit'

        try:
            self.mp_cost = max(0, int(mp_cost))
        except (TypeError, ValueError):
            self.mp_cost = 0
        try:
            self.base_power = int(base_power)
        except (TypeError, ValueError):
            self.base_power = 0
        try:
            self.scaling_factor = float(scaling_factor)
        except (TypeError, ValueError):
            self.scaling_factor = 1.0
        self.scaling_attribute = _resolve_scaling_attribute(
            scaling_attribute, default='int'
        )
        try:
            self.spell_range = max(0, int(spell_range))
        except (TypeError, ValueError):
            self.spell_range = 1

        self.min_power = _optional_int(min_power)
        self.max_power = _optional_int(max_power)
        if (
            self.min_power is not None
            and self.max_power is not None
            and self.min_power > self.max_power
        ):
            self.min_power, self.max_power = self.max_power, self.min_power

        self.usable_in_combat = _parse_bool(usable_in_combat, True)
        self.usable_out_of_combat = _parse_bool(usable_out_of_combat, False)

    def to_client_dict(self):
        return {
            'spell_id': self.id,
            'name': self.name,
            'description': self.description,
            'effect_type': self.effect_type,
            'target_mode': self.target_mode,
            'mp_cost': self.mp_cost,
            'base_power': self.base_power,
            'scaling_attribute': self.scaling_attribute,
            'scaling_factor': self.scaling_factor,
            'hit_rule': self.hit_rule,
            'spell_range': self.spell_range,
            'min_power': self.min_power,
            'max_power': self.max_power,
            'usable_in_combat': self.usable_in_combat,
            'usable_out_of_combat': self.usable_out_of_combat,
        }
