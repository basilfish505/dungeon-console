"""Import SpriteLab monster exports into monster_types.xlsx and static art.

Usage (from the project root):

    py -m monster_types.spritelab_import --init-batch monster_types/spritelab_batches/<new>.json
    py -m monster_types.spritelab_import monster_types/spritelab_batches/<batch>.json --dry-run
    py -m monster_types.spritelab_import monster_types/spritelab_batches/<batch>.json

Two export layouts are supported:

* folder exports: ``<export>/<folder>/sprite.png`` listed in ``manifest.json``;
  a batch entry names the SpriteLab id (``spritelab_id``).
* loose exports: ``<export>/<anything>.png`` (e.g. ``..._cell_07.png``); a batch
  entry names the file (``source``) and pins its content hash (``sha256``).

Every source is identified by the SHA-256 of its PNG bytes, so re-running a
batch skips art that was already imported (under any filename), and a later
export that reuses a generic filename with different art is treated as new
art rather than a duplicate. A pinned ``sha256`` that no longer matches the
file stops the import. The export folder is only ever read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from copy import copy
from datetime import datetime, timezone
from pathlib import Path

from monster_types.sheet import (
    COLUMNS,
    DEFAULT_XLSX_PATH,
    HEADER_COMMENTS,
    PROJECT_ROOT,
    load_monster_sheet,
)

SPRITES_DIR = PROJECT_ROOT / 'static' / 'monsters' / 'sprites'
PORTRAITS_DIR = PROJECT_ROOT / 'static' / 'monsters' / 'portraits'
IMPORT_LOG_PATH = PROJECT_ROOT / 'monster_types' / 'spritelab_imports.json'
DEFAULT_EXPORT_DIR = SPRITES_DIR / 'spritelab_export'
MARKER_PREFIX = 'spritelab:'
HASH_MARKER = 'sha256-'
HASH_MARKER_LEN = 16
REQUIRED_ROW_FIELDS = (
    'type_id', 'name', 'description', 'str', 'int', 'wis', 'chr',
    'dex', 'agi', 'acc', 'base_mhp', 'armour',
)
ZERO_TO_TEN_FIELDS = ('aggression', 'speed', 'activeness')
TYPE_ID_RE = re.compile(r'^[a-z][A-Za-z0-9]*$')
CELL_RE = re.compile(r'cell_(\d+)', re.IGNORECASE)


class ImportErrorList(Exception):
    def __init__(self, errors):
        super().__init__('\n'.join(errors))
        self.errors = errors


# ------------------------------------------------------------------ inputs

def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_manifest(export_dir: Path) -> dict[str, dict]:
    """SpriteLab id -> manifest row. {} when manifest.json is missing or unreadable."""
    path = export_dir / 'manifest.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return {str(row['id']): row for row in data.get('rows') or [] if isinstance(row, dict) and row.get('id')}


def manifest_entry_for_file(manifest: dict[str, dict], filename: str) -> dict | None:
    """Manifest row that mentions this loose file name, if any (metadata only)."""
    for entry in manifest.values():
        if any(isinstance(v, str) and v.replace('\\', '/').endswith(filename) for v in entry.values()):
            return entry
    return None


def load_import_log() -> dict:
    if IMPORT_LOG_PATH.is_file():
        return json.loads(IMPORT_LOG_PATH.read_text(encoding='utf-8'))
    return {'imports': {}}


def imported_hashes(log: dict) -> dict[str, str]:
    """sha256 -> type_id for every logged import (hashing older records' source file)."""
    out = {}
    for record in log['imports'].values():
        digest = record.get('source_sha256')
        if not digest:
            source = PROJECT_ROOT / str(record.get('source_sprite') or '')
            if source.is_file():
                digest = file_sha256(source)
        if digest:
            out[digest] = record.get('type_id')
    return out


def cell_label(filename: str) -> str | None:
    match = CELL_RE.search(filename)
    return match.group(1).zfill(2) if match else None


def loose_sources(export_dir: Path) -> list[Path]:
    return sorted(p for p in export_dir.glob('*.png') if p.is_file())


def resolve_source(export_dir: Path, spec: dict, manifest: dict) -> tuple[str, Path, dict | None]:
    """(import key, source PNG, manifest entry) for one batch entry. Raises ValueError."""
    if spec.get('source'):
        src = export_dir / spec['source']
        if not src.is_file():
            raise ValueError(f'missing {src}')
        digest = file_sha256(src)
        pinned = spec.get('sha256')
        if pinned and pinned != digest:
            raise ValueError(
                f'{spec["source"]} has different art than when the batch was written '
                f'(sha256 {digest[:12]} != pinned {pinned[:12]}); re-run --init-batch'
            )
        return f'{HASH_MARKER}{digest[:HASH_MARKER_LEN]}', src, manifest_entry_for_file(manifest, src.name)
    sid = str(spec.get('spritelab_id') or '')
    if not sid:
        raise ValueError('batch entry needs "source" (loose PNG) or "spritelab_id" (folder export)')
    if sid not in manifest:
        raise ValueError(f'SpriteLab id {sid} is not in {export_dir / "manifest.json"}')
    src = export_dir / manifest[sid]['folder'] / 'sprite.png'
    if not src.is_file():
        raise ValueError(f'missing {src}')
    return sid, src, manifest[sid]


def art_urls(type_id: str) -> tuple[str, str]:
    return (
        f'/static/monsters/sprites/{type_id}.png',
        f'/static/monsters/portraits/{type_id}.png',
    )


def url_to_path(url: str) -> Path:
    return PROJECT_ROOT / url.lstrip('/').replace('/', os.sep)


# ---------------------------------------------------------------- workbook

def _monster_sheet(wb):
    return wb['Monsters'] if 'Monsters' in wb.sheetnames else wb.active


def _header_index(ws) -> dict[str, int]:
    return {
        str(cell.value).strip(): cell.column
        for cell in ws[1]
        if cell.value is not None and str(cell.value).strip()
    }


def existing_entries(ws, headers):
    """(type_ids, spritelab marker ids, last_data_row) currently in the sheet."""
    type_col = headers['type_id']
    notes_col = headers.get('spawn_notes')
    type_ids, marker_ids, last_row = set(), set(), 1
    for row in range(2, ws.max_row + 1):
        value = ws.cell(row, type_col).value
        if value is None or not str(value).strip():
            continue
        last_row = row
        type_ids.add(str(value).strip().lower())
        if notes_col:
            notes = str(ws.cell(row, notes_col).value or '')
            for part in notes.replace('|', ' ').split():
                if part.startswith(MARKER_PREFIX):
                    marker_ids.add(part[len(MARKER_PREFIX):])
    return type_ids, marker_ids, last_row


def _copy_style(src, dst):
    if src.has_style:
        dst.font = copy(src.font)
        dst.border = copy(src.border)
        dst.fill = copy(src.fill)
        dst.alignment = copy(src.alignment)
        dst.number_format = src.number_format
        dst.protection = copy(src.protection)


def ensure_sheet_columns(ws) -> list[str]:
    """Append COLUMNS missing from the header row (styled like the last column).

    Returns the names added. Existing columns, rows and styles are untouched.
    """
    from openpyxl.comments import Comment
    from openpyxl.utils import get_column_letter

    headers = _header_index(ws)
    missing = [c for c in COLUMNS if c not in headers]
    if not missing:
        return []
    last_col = max(headers.values())
    for offset, name in enumerate(missing, 1):
        col = last_col + offset
        letter = get_column_letter(col)
        header = ws.cell(1, col, name)
        _copy_style(ws.cell(1, last_col), header)
        if HEADER_COMMENTS.get(name):
            header.comment = Comment(HEADER_COMMENTS[name], 'dungeon-console')
        for row in range(2, ws.max_row + 1):
            _copy_style(ws.cell(row, last_col), ws.cell(row, col))
        ws.column_dimensions[letter].width = 16
    if ws.auto_filter.ref:
        from openpyxl.utils import range_boundaries
        min_col, min_row, _max_col, max_row = range_boundaries(ws.auto_filter.ref)
        ws.auto_filter.ref = (
            f'{get_column_letter(min_col)}{min_row}:{get_column_letter(last_col + len(missing))}{max_row}'
        )
    return missing


def save_workbook(wb, xlsx_path: Path) -> Path:
    """Back up to <name>.bak, then save atomically. Returns the backup path."""
    backup = xlsx_path.with_name(xlsx_path.name + '.bak')
    shutil.copy2(xlsx_path, backup)
    fd, tmp = tempfile.mkstemp(suffix='.xlsx', dir=xlsx_path.parent)
    os.close(fd)
    try:
        wb.save(tmp)
        os.replace(tmp, xlsx_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return backup


# -------------------------------------------------------------- validation

def validate_row(row: dict) -> list[str]:
    from monster_types.references import row_reference_errors

    tid = row.get('type_id') or '?'
    errors = []
    for field in REQUIRED_ROW_FIELDS:
        if row.get(field) in (None, ''):
            errors.append(f'{tid}: missing required field {field}')
    if row.get('type_id') and not TYPE_ID_RE.match(str(row['type_id'])):
        errors.append(f'{tid}: type_id must be camelCase letters/digits (e.g. ironbackBeetle)')
    unknown = sorted(set(row) - set(COLUMNS))
    if unknown:
        errors.append(f'{tid}: unknown columns {unknown}')
    for field in ZERO_TO_TEN_FIELDS:
        value = row.get(field)
        if value not in (None, '') and not 0 <= float(value) <= 10:
            errors.append(f'{tid}: {field} must be 0-10, got {value}')
    errors.extend(row_reference_errors(row, str(tid)))
    if _csv(row.get('spells')) and not int(row.get('base_mmp') or 0):
        errors.append(f'{tid}: has spells but base_mmp is 0')
    return errors


def _csv(value):
    return [p.strip() for p in str(value or '').split(',') if p.strip()]


# ------------------------------------------------------------------- art

def write_square_png(src: Path, dst: Path) -> None:
    """Pad onto a transparent square canvas (centred, feet on the bottom edge).

    The map draws sprites into square tiles, so non-square art would stretch.
    Pixels are copied, never resampled.
    """
    from PIL import Image

    with Image.open(src) as img:
        img = img.convert('RGBA')
        side = max(img.size)
        canvas = Image.new('RGBA', (side, side), (0, 0, 0, 0))
        canvas.paste(img, ((side - img.width) // 2, side - img.height))
        dst.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(dst)


def write_contact_sheet(tiles: list[tuple[Path, list[str]]], out: Path, cell: int = 168) -> Path:
    """Grid of images, each enlarged with nearest-neighbour and captioned.

    ``tiles`` is [(image path, caption lines)].
    """
    from PIL import Image, ImageDraw

    line_h = 14
    label_h = 6 + line_h * max((len(lines) for _p, lines in tiles), default=1)
    cols = min(5, max(1, len(tiles)))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGBA', (cols * cell, rows * (cell + label_h)), (32, 26, 22, 255))
    draw = ImageDraw.Draw(sheet)
    for i, (path, lines) in enumerate(tiles):
        x, y = (i % cols) * cell, (i // cols) * (cell + label_h)
        draw.rectangle([x + 4, y + 4, x + cell - 5, y + cell - 5], fill=(52, 44, 38, 255))
        with Image.open(path) as img:
            img = img.convert('RGBA')
            scale = max(1, (cell - 12) // max(img.size))
            img = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
            sheet.paste(img, (x + (cell - img.width) // 2, y + (cell - img.height) // 2), img)
        for j, line in enumerate(lines):
            draw.text((x + 6, y + cell + 2 + j * line_h), line, fill=(244, 232, 208, 255))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def write_final_contact_sheet(batch: dict, out: Path, xlsx_path: Path = DEFAULT_XLSX_PATH) -> Path:
    """Contact sheet of the art the game will actually load for each batch row."""
    by_id = {t.id: t for t in load_monster_sheet(xlsx_path, register=False)}
    tiles = []
    for spec in batch.get('monsters') or []:
        tid = (spec.get('row') or {}).get('type_id')
        td = by_id.get(tid)
        if td is None:
            continue
        sprite = url_to_path(td.sprite)
        label = f"cell {spec['cell']}" if spec.get('cell') else (spec.get('spritelab_id') or '')[:8]
        tiles.append((sprite, [f'{label}: {td.name}', sprite.name]))
    return write_contact_sheet(tiles, out)


# ------------------------------------------------------------------ import

def import_batch(batch_path: Path, *, xlsx_path: Path = DEFAULT_XLSX_PATH, dry_run=False):
    """Import one batch. Returns a list of (status, type_id, detail) tuples."""
    from openpyxl import load_workbook

    batch = json.loads(batch_path.read_text(encoding='utf-8'))
    export_dir = PROJECT_ROOT / batch.get('export_dir', str(DEFAULT_EXPORT_DIR))
    manifest = load_manifest(export_dir)
    log = load_import_log()
    known_hashes = imported_hashes(log)

    wb = load_workbook(xlsx_path)
    ws = _monster_sheet(wb)
    added_columns = ensure_sheet_columns(ws)
    headers = _header_index(ws)
    type_ids, marked_ids, last_row = existing_entries(ws, headers)

    report, pending, errors = [], [], []
    batch_type_ids, batch_hashes = set(), {}
    for column in added_columns:
        report.append(('column', column, f'added to {xlsx_path.name}'))
    for spec in batch.get('monsters') or []:
        row = dict(spec.get('row') or {})
        tid = str(row.get('type_id') or '').strip()
        key = tid.lower()
        sid = str(spec.get('spritelab_id') or '')
        if sid and (sid in log['imports'] or sid in marked_ids):
            report.append(('skip', tid, f'SpriteLab {sid[:8]} already imported'))
            continue
        try:
            import_key, src, entry = resolve_source(export_dir, spec, manifest)
        except ValueError as exc:
            errors.append(f'{tid or "?"}: {exc}')
            continue
        digest = file_sha256(src)
        if import_key in log['imports'] or import_key in marked_ids:
            report.append(('skip', tid, f'{src.name} already imported'))
            continue
        if digest in known_hashes:
            report.append(('skip', tid, f'{src.name}: same art already imported as {known_hashes[digest]}'))
            continue
        if key in type_ids:
            report.append(('skip', tid, 'type_id already in the sheet'))
            continue
        if key in batch_type_ids:
            errors.append(f'{tid}: duplicate type_id within the batch')
            continue
        if digest in batch_hashes:
            errors.append(f'{tid}: {src.name} has the same art as {batch_hashes[digest]} in this batch')
            continue
        batch_type_ids.add(key)
        batch_hashes[digest] = tid
        sprite_url, portrait_url = art_urls(tid)
        for url in (sprite_url, portrait_url):
            if url_to_path(url).exists():
                errors.append(f'{tid}: {url} already exists; refusing to overwrite art')
        errors.extend(validate_row(row))
        row['sprite'], row['portrait'] = sprite_url, portrait_url
        notes = [f'{MARKER_PREFIX}{import_key}']
        if spec.get('cell'):
            notes.append(f"cell {spec['cell']}")
        if spec.get('balance_reference'):
            notes.append(f"balance ref: {spec['balance_reference']}")
        if spec.get('role'):
            notes.append(spec['role'])
        row['spawn_notes'] = ' | '.join(notes)
        pending.append((import_key, entry, src, digest, row, spec))

    if errors:
        raise ImportErrorList(errors)
    if dry_run:
        report.extend(
            ('would add', p[4]['type_id'], f'row {last_row + i} <- {p[2].name}')
            for i, p in enumerate(pending, 1)
        )
        return report
    if not pending and not added_columns:
        return report

    style_row = last_row if last_row >= 2 else 2
    for offset, (*_ignored, row, _spec) in enumerate(pending, 1):
        target = last_row + offset
        for name in COLUMNS:
            col = headers[name]
            cell = ws.cell(target, col)
            _copy_style(ws.cell(style_row, col), cell)
            value = row.get(name)
            cell.value = None if value == '' else value
    _grow_autofilter(ws, last_row + len(pending))
    backup = save_workbook(wb, xlsx_path)

    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for offset, (import_key, entry, src, digest, row, spec) in enumerate(pending, 1):
        write_square_png(src, url_to_path(row['sprite']))
        write_square_png(src, url_to_path(row['portrait']))
        record = {
            'type_id': row['type_id'],
            'name': row['name'],
            'batch': batch.get('batch') or batch_path.stem,
            'source_file': src.name,
            'source_sprite': src.relative_to(PROJECT_ROOT).as_posix(),
            'source_sha256': digest,
            'sprite': row['sprite'],
            'portrait': row['portrait'],
            'balance_reference': spec.get('balance_reference'),
            'imported_at': now,
        }
        if spec.get('cell'):
            record['cell'] = spec['cell']
        if entry and entry.get('folder'):
            record['export_folder'] = entry['folder']
        log['imports'][import_key] = record
        report.append(('added', row['type_id'], f'row {last_row + offset} <- {src.name}'))
    IMPORT_LOG_PATH.write_text(json.dumps(log, indent=2) + '\n', encoding='utf-8')

    try:
        verify_import([p[4]['type_id'] for p in pending], xlsx_path)
    except ImportErrorList as exc:
        raise ImportErrorList(
            [f'Rows were written but verification failed (backup: {backup.name}):'] + exc.errors
        ) from None
    return report


def _grow_autofilter(ws, last_row):
    from openpyxl.utils import range_boundaries, get_column_letter

    ref = ws.auto_filter.ref
    if not ref:
        return
    min_col, min_row, max_col, max_row = range_boundaries(ref)
    if last_row > max_row:
        ws.auto_filter.ref = (
            f'{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{last_row}'
        )


def verify_import(type_ids, xlsx_path=DEFAULT_XLSX_PATH):
    """Reload through the game's own loader and check ids, art paths and references."""
    from monster_types.references import sheet_reference_errors

    types = load_monster_sheet(xlsx_path, register=False)
    ids = [t.id for t in types]
    errors = []
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f'duplicate type_ids in sheet: {dupes}')
    by_id = {t.id: t for t in types}
    for tid in type_ids:
        td = by_id.get(tid)
        if td is None:
            errors.append(f'{tid}: not readable by load_monster_sheet')
            continue
        for url in (td.sprite, td.portrait):
            if not url_to_path(url).is_file():
                errors.append(f'{tid}: {url} does not resolve')
    errors.extend(sheet_reference_errors(xlsx_path))
    if errors:
        raise ImportErrorList(errors)
    return [by_id[t] for t in type_ids]


def init_batch(out_path: Path, export_dir: Path = DEFAULT_EXPORT_DIR) -> tuple[Path, Path | None]:
    """Write a skeleton batch for exports not imported yet, plus a captioned contact sheet."""
    manifest = load_manifest(export_dir)
    log = load_import_log()
    known_hashes = imported_hashes(log)
    entries, tiles = [], []
    blank_row = {c: '' for c in COLUMNS if c not in ('sprite', 'portrait', 'spawn_notes')}
    blank_row['weapon'] = 'unarmed'
    for sid, entry in manifest.items():
        src = export_dir / str(entry.get('folder', '')) / 'sprite.png'
        if sid in log['imports'] or not src.is_file() or file_sha256(src) in known_hashes:
            continue
        entries.append({'spritelab_id': sid, 'prompt': entry.get('prompt'), 'row': dict(blank_row)})
        tiles.append((src, [f'{len(entries)}. {sid[:8]}']))
    for src in loose_sources(export_dir):
        digest = file_sha256(src)
        if digest in known_hashes:
            continue
        cell = cell_label(src.name)
        meta = manifest_entry_for_file(manifest, src.name)
        spec = {'source': src.name, 'sha256': digest}
        if cell:
            spec['cell'] = cell
        if meta and meta.get('prompt'):
            spec['prompt'] = meta['prompt']
        spec.update({'role': '', 'balance_reference': '', 'row': dict(blank_row)})
        entries.append(spec)
        tiles.append((src, [f'cell {cell}' if cell else src.stem[:20], src.name[-22:]]))
    batch = {
        'batch': out_path.stem,
        'export_dir': export_dir.relative_to(PROJECT_ROOT).as_posix(),
        'monsters': entries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(batch, indent=2) + '\n', encoding='utf-8')
    sheet = write_contact_sheet(tiles, out_path.with_suffix('.contact_sheet.png')) if tiles else None
    return out_path, sheet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('batch', nargs='?', help='Batch JSON to import')
    parser.add_argument('--dry-run', action='store_true', help='Validate and report without writing')
    parser.add_argument('--init-batch', metavar='PATH', help='Write a skeleton batch + contact sheet for unimported exports')
    parser.add_argument('--export-dir', default=str(DEFAULT_EXPORT_DIR), help='SpriteLab export folder (for --init-batch)')
    args = parser.parse_args(argv)

    if args.init_batch:
        out, sheet = init_batch(Path(args.init_batch).resolve(), Path(args.export_dir).resolve())
        print(f'Wrote {out}')
        print(f'Contact sheet: {sheet}' if sheet else 'Every export is already imported.')
        return 0
    if not args.batch:
        parser.error('give a batch JSON or --init-batch PATH')
    batch_path = Path(args.batch).resolve()
    try:
        report = import_batch(batch_path, dry_run=args.dry_run)
    except ImportErrorList as exc:
        print('Import failed:', file=sys.stderr)
        for err in exc.errors:
            print(f'  - {err}', file=sys.stderr)
        return 1
    for status, tid, detail in report:
        print(f'{status:9} {tid:18} {detail}')
    if not report:
        print('Batch is empty.')
    if not args.dry_run:
        batch = json.loads(batch_path.read_text(encoding='utf-8'))
        sheet = write_final_contact_sheet(batch, batch_path.with_suffix('.final_contact_sheet.png'))
        print(f'Final contact sheet (art the game loads): {sheet}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
