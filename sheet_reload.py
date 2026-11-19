"""Re-read every spreadsheet definition into its live registry.

The game loads monster_types.xlsx, spell_types.xlsx, item_types.xlsx,
weapon_types.xlsx and armour_types.xlsx once at import. Starting a new world
calls reload_all_sheets() so balance edits apply without restarting the server.

Each sheet is parsed completely before its registry is touched, so a missing,
locked or broken workbook leaves the definitions already loaded untouched and
never blocks the other sheets. Rows are updated in place (new rows added,
existing rows overwritten); a row deleted from a sheet stays registered until
the next restart.
"""

from __future__ import annotations


def reload_sheet(label, sheet_module, register):
    """
    Re-read one sheet's default workbook into its registry.

    ``sheet_module`` is the module that owns DEFAULT_XLSX_PATH,
    iter_xlsx_rows and typedefs_from_rows; ``register`` adds one definition
    to the registry. Returns the number of definitions loaded, or None when
    the reload was skipped (missing or unreadable workbook).
    """
    path = sheet_module.DEFAULT_XLSX_PATH
    if not path.is_file():
        print(f'[{label}] reload skipped: missing {path}')
        return None
    try:
        type_defs = sheet_module.typedefs_from_rows(sheet_module.iter_xlsx_rows(path))
    except Exception as exc:
        print(f'[{label}] reload failed ({exc}); keeping the definitions already loaded')
        return None
    for type_def in type_defs:
        register(type_def)
    print(f'[{label}] reloaded {len(type_defs)} definitions from {path.name}')
    return len(type_defs)


def reload_all_sheets():
    """Reload all five sheets. Returns {label: count or None}."""
    from armour_types import sheet as armour_sheet
    from armour_types.registry import register_armour_type
    from item_types import sheet as item_sheet
    from item_types.registry import register_item_type
    from monster_types import sheet as monster_sheet
    from monster_types.registry import register_monster_type
    from spell_types import sheet as spell_sheet
    from spell_types.registry import register_spell_type
    from weapon_types import sheet as weapon_sheet
    from weapon_types.registry import register_weapon_type

    sheets = (
        ('monster_types', monster_sheet, register_monster_type),
        ('spell_types', spell_sheet, register_spell_type),
        ('item_types', item_sheet, register_item_type),
        ('weapon_types', weapon_sheet, register_weapon_type),
        ('armour_types', armour_sheet, register_armour_type),
    )
    return {
        label: reload_sheet(label, module, register)
        for label, module, register in sheets
    }
