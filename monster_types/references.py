"""Cross-sheet reference checks for monster_types.xlsx.

A monster row points at other spreadsheets: ``weapon`` (weapon_types.xlsx),
``spells`` (spell_types.xlsx), ``ability_ids`` (abilities.xlsx) and ``loot``
(item / weapon / armour sheets). Unknown ids never crash the game (they are
skipped at runtime), so these checks exist to tell the designer which row and
which id is wrong.
"""

from __future__ import annotations

from pathlib import Path

from monster_types.base import UNARMED_WEAPON_CHOICE

FIRST_DATA_ROW = 2


def _csv(value):
    return [p.strip() for p in str(value or '').split(',') if p.strip()]


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def row_reference_errors(row, where):
    """Unknown weapon / spell / ability / loot ids in one row -> list of messages.

    ``where`` prefixes each message, e.g. "monster_types.xlsx row 21 (type_id 'x')".
    """
    import abilities  # noqa: F401 - load abilities.xlsx into the registry
    import spell_types  # noqa: F401 - load spell_types.xlsx into the registry
    import weapon_types  # noqa: F401 - load weapon_types.xlsx into the registry
    from abilities.registry import get_ability
    from items.catalog import resolve_loot_type
    from spell_types.registry import get_spell_type
    from weapon_types.registry import get_weapon_type

    errors = []
    weapon = row.get('weapon')
    if not _blank(weapon):
        weapon = str(weapon).strip()
        if weapon.lower() != UNARMED_WEAPON_CHOICE and get_weapon_type(weapon) is None:
            errors.append(
                f"{where}: unknown weapon {weapon!r} "
                f"(use a weapon_id from weapon_types.xlsx, '{UNARMED_WEAPON_CHOICE}', or leave blank)"
            )
    for spell_id in _csv(row.get('spells')):
        if get_spell_type(spell_id) is None:
            errors.append(f'{where}: unknown spell id {spell_id!r}')
    for ability_id in _csv(row.get('ability_ids')):
        if get_ability(ability_id) is None:
            errors.append(f'{where}: unknown ability id {ability_id!r}')
    for loot_id in _csv(row.get('loot')):
        if resolve_loot_type(loot_id) is None:
            errors.append(f'{where}: unknown loot id {loot_id!r}')
    return errors


def sheet_reference_errors(path):
    """Check every monster row in a workbook. Returns a list of messages."""
    from monster_types.sheet import iter_xlsx_rows

    path = Path(path)
    errors = []
    for row_number, row in enumerate(iter_xlsx_rows(path), FIRST_DATA_ROW):
        type_id = row.get('type_id')
        if _blank(type_id):
            continue
        where = f'{path.name} row {row_number} (type_id {str(type_id).strip()!r})'
        errors.extend(row_reference_errors(row, where))
    return errors


def report_reference_errors(path):
    """Print reference problems; never raises. Returns the messages."""
    try:
        errors = sheet_reference_errors(path)
    except Exception as exc:
        print(f'[monster_types] reference check skipped: {exc}')
        return []
    for message in errors:
        print(f'[monster_types] {message}')
    return errors
