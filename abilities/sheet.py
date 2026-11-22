"""Load and write the abilities spreadsheet (abilities.xlsx, sheet "Abilities").

One row per ability. Monsters list ability ids in the ability_ids column of
monster_types.xlsx; several monsters may share an ability and a monster may
have several. Rows that fail validation are reported with their row number
and skipped, so a monster pointing at them is reported as an unknown id too.
"""

from __future__ import annotations

from pathlib import Path

from abilities.base import Ability
from abilities.handlers import EFFECT_HANDLERS, get_handler
from abilities.registry import register_ability

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX_PATH = PROJECT_ROOT / 'abilities.xlsx'
SHEET_NAME = 'Abilities'
FIRST_DATA_ROW = 2
ROW_KEY = '_row'

COLUMNS = [
    'ability_id',
    'name',
    'description',
    'handler',
    'params',
    'notes',
]

HEADER_COMMENTS = {
    'ability_id': 'Stable machine id, lowercase snake_case (e.g. venom_bite). Required. '
                  'Put this id in the ability_ids column of monster_types.xlsx.',
    'name': 'Display name shown when a monster is inspected. Required.',
    'description': 'Inspect / flavor text.',
    'handler': 'Effect handler from the Handlers sheet (e.g. poison). Required. '
               'Handlers marked "planned" load but do nothing in combat yet.',
    'params': 'Handler parameters as key=value pairs separated by semicolons, '
              'e.g. chance=25; damage=2; turns=3. Allowed keys are on the Handlers sheet.',
    'notes': 'Design notes only; not loaded into the game.',
}

EXAMPLE_ABILITIES = [
    {
        'ability_id': 'venom_bite',
        'name': 'Venom Bite',
        'description': 'A bite that can leave the victim poisoned.',
        'handler': 'poison',
        'params': 'chance=25; damage=2; turns=3',
        'notes': 'Example row. Inactive until the poison handler is implemented.',
    },
    {
        'ability_id': 'blood_drinker',
        'name': 'Blood Drinker',
        'description': 'Heals itself with part of the damage it deals.',
        'handler': 'lifesteal',
        'params': 'percent=30',
        'notes': 'Example row. Inactive until the lifesteal handler is implemented.',
    },
]


def _blank(value):
    return value is None or (isinstance(value, str) and not value.strip())


def _str_or_none(value):
    return None if _blank(value) else str(value).strip()


def parse_params(text):
    """'chance=25; damage=2' -> {'chance': '25', 'damage': '2'}. Raises ValueError."""
    params = {}
    if _blank(text):
        return params
    for part in str(text).split(';'):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition('=')
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            raise ValueError(f'malformed parameter {part!r} (expected key=value)')
        if key in params:
            raise ValueError(f'parameter {key!r} given twice')
        params[key] = value
    return params


def _convert_params(raw, handler):
    params = {}
    for key, value in raw.items():
        kind = handler.params.get(key)
        if kind is None:
            allowed = ', '.join(sorted(handler.params)) or 'none'
            raise ValueError(f'unknown parameter {key!r} for handler {handler.name!r} (allowed: {allowed})')
        try:
            params[key] = kind(float(value)) if kind is int else kind(value)
        except (TypeError, ValueError):
            raise ValueError(f'parameter {key}={value!r} is not a valid {kind.__name__}') from None
    return params


def row_to_ability(row, where='abilities.xlsx'):
    """Build an Ability from one row dict. None for blank rows; raises ValueError."""
    ability_id = _str_or_none(row.get('ability_id'))
    if not ability_id:
        return None
    handler_name = _str_or_none(row.get('handler'))
    if not handler_name:
        raise ValueError('missing handler')
    handler = get_handler(handler_name)
    if handler is None:
        known = ', '.join(sorted(EFFECT_HANDLERS))
        raise ValueError(f'unknown handler {handler_name!r} (known: {known})')
    params = _convert_params(parse_params(row.get('params')), handler)
    return Ability(
        ability_id,
        name=_str_or_none(row.get('name')) or ability_id,
        description=_str_or_none(row.get('description')),
        handler=handler.name,
        params=params,
        source_row=row.get(ROW_KEY),
    )


def iter_xlsx_rows(path):
    """Yield one dict per data row, with its sheet row number under ROW_KEY."""
    from openpyxl import load_workbook

    wb = load_workbook(Path(path), data_only=True, read_only=True)
    try:
        ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.active
        rows = ws.iter_rows(values_only=True)
        header_row = next(rows, None)
        if not header_row:
            return
        headers = ['' if h is None else str(h).strip() for h in header_row]
        for row_number, values in enumerate(rows, FIRST_DATA_ROW):
            row = {
                headers[i]: values[i] if i < len(values) else None
                for i in range(len(headers))
                if headers[i]
            }
            row[ROW_KEY] = row_number
            yield row
    finally:
        wb.close()


def build_abilities(rows, filename='abilities.xlsx'):
    """(abilities, errors) from row dicts. Invalid and duplicate rows are skipped."""
    abilities, errors, seen = [], [], {}
    for row in rows:
        ability_id = _str_or_none(row.get('ability_id'))
        if not ability_id:
            continue
        where = f'{filename} row {row.get(ROW_KEY, "?")} (ability_id {ability_id!r})'
        if ability_id in seen:
            errors.append(f'{where}: duplicate ability_id (first defined on row {seen[ability_id]})')
            continue
        try:
            ability = row_to_ability(row)
        except ValueError as exc:
            errors.append(f'{where}: {exc}')
            continue
        seen[ability_id] = row.get(ROW_KEY, '?')
        abilities.append(ability)
    return abilities, errors


def typedefs_from_rows(rows):
    """sheet_reload entry point: valid abilities; problems are printed."""
    abilities, errors = build_abilities(rows, DEFAULT_XLSX_PATH.name)
    for message in errors:
        print(f'[abilities] {message}')
    return abilities


def ability_sheet_errors(path=DEFAULT_XLSX_PATH):
    path = Path(path)
    return build_abilities(iter_xlsx_rows(path), path.name)[1]


def load_ability_sheet(path, register=True):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    abilities, errors = build_abilities(iter_xlsx_rows(path), path.name)
    for message in errors:
        print(f'[abilities] {message}')
    if register:
        for ability in abilities:
            register_ability(ability)
    return abilities


def load_default_ability_sheet():
    if not DEFAULT_XLSX_PATH.is_file():
        print(f'[abilities] missing {DEFAULT_XLSX_PATH}; no abilities loaded')
        return []
    try:
        return load_ability_sheet(DEFAULT_XLSX_PATH)
    except ImportError as exc:
        print(f'[abilities] cannot load {DEFAULT_XLSX_PATH}: {exc}. Install openpyxl (pip install openpyxl)')
        return []
    except Exception as exc:
        print(f'[abilities] failed to load {DEFAULT_XLSX_PATH}: {exc}')
        return []


def write_ability_xlsx(path=None, extra_rows=None):
    """Create the fill-in workbook (Abilities + Handlers + Instructions + Field reference)."""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    path = Path(path) if path else DEFAULT_XLSX_PATH
    wb = Workbook()

    thin = Border(
        left=Side(style='thin', color='C4B8A8'),
        right=Side(style='thin', color='C4B8A8'),
        top=Side(style='thin', color='C4B8A8'),
        bottom=Side(style='thin', color='C4B8A8'),
    )
    header_fill = PatternFill('solid', fgColor='3D2B1F')
    header_font = Font(bold=True, color='F4E8D0', name='Calibri', size=11)
    example_fill = PatternFill('solid', fgColor='E6F4EA')
    wrap = Alignment(wrap_text=True, vertical='center')

    def header_row(ws, headers, comments=None):
        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(1, col_idx, header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = thin
            note = (comments or {}).get(header)
            if note:
                cell.comment = Comment(note, 'dungeon-console')
        ws.freeze_panes = 'A2'
        ws.row_dimensions[1].height = 22

    ws = wb.active
    ws.title = SHEET_NAME
    header_row(ws, COLUMNS, HEADER_COMMENTS)
    data_rows = list(EXAMPLE_ABILITIES) + list(extra_rows or [])
    for row_idx, row in enumerate(data_rows, FIRST_DATA_ROW):
        for col_idx, header in enumerate(COLUMNS, 1):
            cell = ws.cell(row_idx, col_idx, row.get(header, ''))
            cell.border = thin
            cell.alignment = wrap
            if row_idx < FIRST_DATA_ROW + len(EXAMPLE_ABILITIES):
                cell.fill = example_fill
    last_data = 1 + max(40, len(data_rows))
    for row_idx in range(FIRST_DATA_ROW + len(data_rows), last_data + 1):
        for col_idx in range(1, len(COLUMNS) + 1):
            ws.cell(row_idx, col_idx, None).border = thin
    widths = {'ability_id': 18, 'name': 18, 'description': 44, 'handler': 14, 'params': 32, 'notes': 40}
    for col_idx, header in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(header, 12)
    ws.auto_filter.ref = f'A1:{get_column_letter(len(COLUMNS))}{last_data}'
    ws.sheet_properties.tabColor = '3D2B1F'

    handlers = wb.create_sheet('Handlers')
    header_row(handlers, ('handler', 'status', 'params', 'description'))
    for row_idx, handler in enumerate(sorted(EFFECT_HANDLERS.values(), key=lambda h: h.name), 2):
        values = (
            handler.name,
            'implemented' if handler.implemented else 'planned (inactive)',
            ', '.join(f'{k} ({t.__name__})' for k, t in handler.params.items()),
            handler.description,
        )
        for col_idx, value in enumerate(values, 1):
            cell = handlers.cell(row_idx, col_idx, value)
            cell.border = thin
            cell.alignment = wrap
    for letter, width in zip('ABCD', (16, 20, 40, 56)):
        handlers.column_dimensions[letter].width = width

    ins = wb.create_sheet('Instructions')
    ins['A1'] = 'How to use'
    ins['A1'].font = Font(bold=True, size=14, color='3D2B1F')
    instructions = [
        '',
        '1. One row per ability on the Abilities sheet (the green rows are examples).',
        '2. Required: ability_id, name, handler. ability_id must be unique.',
        '3. handler must be a name from the Handlers sheet. params are key=value pairs separated by semicolons.',
        '4. Give a monster abilities by listing ability ids in the ability_ids column of monster_types.xlsx '
        '(comma-separated, e.g. venom_bite, blood_drinker). Several monsters can share one ability.',
        '5. A handler marked "planned (inactive)" has no code yet: the ability loads and shows as '
        '"(inactive)" on inspect, but does nothing in combat until the handler is implemented.',
        '6. Save, then start a new world (or restart the game). Problems are printed as '
        '"[abilities] abilities.xlsx row N (ability_id ...): ..." and that row is skipped.',
        '7. notes is for your own comments and is not loaded.',
    ]
    for idx, line in enumerate(instructions, 2):
        ins[f'A{idx}'] = line
        ins[f'A{idx}'].alignment = Alignment(wrap_text=True)
    ins.column_dimensions['A'].width = 110

    ref = wb.create_sheet('Field reference')
    header_row(ref, ('column', 'required', 'type', 'notes'))
    fields = [
        ('ability_id', 'yes', 'string', 'Unique machine id, referenced from monster_types.xlsx ability_ids'),
        ('name', 'yes', 'string', 'Display name'),
        ('description', 'no', 'string', 'Inspect text'),
        ('handler', 'yes', 'handler name', 'See the Handlers sheet'),
        ('params', 'no', 'key=value; key=value', 'Keys and types per handler (Handlers sheet). Blank = none'),
        ('notes', 'no', 'text', 'Ignored on import'),
    ]
    for row_idx, values in enumerate(fields, 2):
        for col_idx, value in enumerate(values, 1):
            cell = ref.cell(row_idx, col_idx, value)
            cell.border = thin
            cell.alignment = wrap
    for letter, width in zip('ABCD', (16, 12, 22, 60)):
        ref.column_dimensions[letter].width = width

    wb.save(path)
    return path
