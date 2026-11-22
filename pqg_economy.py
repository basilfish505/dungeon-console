"""Server-authoritative PQG ledger and account balances.

Gameplay mutates PQG only through ``credit`` / ``debit``. The ledger row is
the source of truth; ``pqg_balances.balance`` is a cached total written in the
same store transaction. ``player.pqg`` is a display cache kept in sync after
each successful ledger write.
"""

from __future__ import annotations

import uuid
from typing import Any

ENTRY_ISSUANCE = 'issuance'
ENTRY_SPEND = 'spend'
ENTRY_ADJUSTMENT = 'adjustment'

SOURCE_MONSTER_KILL = 'monster_kill'
SOURCE_LOOT_CHEST = 'loot_chest'
SOURCE_SHOP_PURCHASE = 'shop_purchase'
SOURCE_INN_STAY = 'inn_stay'
SOURCE_STARTING_GRANT = 'starting_grant'
SOURCE_MIGRATION = 'migration'

STATUS_COMMITTED = 'committed'


def new_account_id() -> str:
    return uuid.uuid4().hex


def new_event_id() -> str:
    return uuid.uuid4().hex


def kill_idempotency_key(kill_id: str, *, share_player_id: str | None = None) -> str:
    kid = str(kill_id or '').strip()
    if share_player_id:
        return f'kill:{kid}:share:{share_player_id}'
    return f'kill:{kid}'


def chest_idempotency_key(
    world_id, level, slot_id, claim_seq, *, what: str, item_uid: str | None = None
) -> str:
    base = (
        f'chest:{world_id}:{int(level)}:{slot_id}:{int(claim_seq)}:{what}'
    )
    if what == 'item' and item_uid:
        return f'{base}:{item_uid}'
    return base


def ensure_account(store, account_id: str | None = None) -> str:
    """Create an account (and zero balance) if needed. Returns account_id."""
    aid = str(account_id or '').strip() or new_account_id()
    store.create_account(aid)
    store.ensure_pqg_balance(aid)
    return aid


def get_balance(store, account_id: str) -> int:
    if not account_id:
        return 0
    return int(store.get_pqg_balance(account_id) or 0)


def sync_player_pqg(player, store) -> int:
    """Refresh ``player.pqg`` from the authoritative balance. Returns balance."""
    if player is None:
        return 0
    account_id = getattr(player, 'account_id', None)
    if not account_id:
        return int(getattr(player, 'pqg', 0) or 0)
    balance = get_balance(store, account_id)
    player.pqg = balance
    return balance


def _apply(
    store,
    *,
    account_id: str,
    amount: int,
    entry_type: str,
    source: str,
    idempotency_key: str,
    source_instance_id: str | None = None,
    world_id: str | None = None,
    character_id: str | None = None,
    dungeon_level: int | None = None,
    monster_type_id: str | None = None,
    monster_elo: float | None = None,
    chest_slot_id: str | None = None,
    metadata: dict | None = None,
    player=None,
) -> dict[str, Any]:
    """
    Insert one ledger row and update the cached balance atomically.

    Returns ``{ok, already_applied, balance, event_id, message}``.
    """
    result = {
        'ok': False,
        'already_applied': False,
        'balance': 0,
        'event_id': None,
        'message': None,
        'amount': int(amount),
    }
    aid = str(account_id or '').strip()
    key = str(idempotency_key or '').strip()
    if not aid or not key:
        result['message'] = 'Missing account or idempotency key.'
        return result
    try:
        delta = int(amount)
    except (TypeError, ValueError):
        result['message'] = 'Invalid amount.'
        return result
    if delta == 0:
        result['ok'] = True
        result['balance'] = get_balance(store, aid)
        result['message'] = 'No-op amount.'
        if player is not None:
            player.pqg = result['balance']
        return result

    ensure_account(store, aid)
    event_id = new_event_id()
    try:
        outcome = store.apply_pqg_ledger_entry(
            event_id=event_id,
            account_id=aid,
            amount=delta,
            entry_type=entry_type,
            source=source,
            idempotency_key=key,
            source_instance_id=source_instance_id,
            world_id=world_id,
            character_id=character_id,
            dungeon_level=dungeon_level,
            monster_type_id=monster_type_id,
            monster_elo=monster_elo,
            chest_slot_id=chest_slot_id,
            metadata=metadata or {},
        )
    except InsufficientPqgError as exc:
        result['message'] = str(exc) or 'Insufficient PQG.'
        result['balance'] = get_balance(store, aid)
        if player is not None:
            player.pqg = result['balance']
        return result

    if outcome.get('already_applied'):
        result['ok'] = True
        result['already_applied'] = True
        result['balance'] = int(outcome.get('balance') or get_balance(store, aid))
        result['event_id'] = outcome.get('event_id')
        result['message'] = 'Already applied.'
        if player is not None:
            player.pqg = result['balance']
        return result

    result['ok'] = True
    result['balance'] = int(outcome['balance'])
    result['event_id'] = outcome.get('event_id') or event_id
    if player is not None:
        player.pqg = result['balance']
    return result


def credit(
    store,
    account_id: str,
    amount: int,
    *,
    source: str,
    idempotency_key: str,
    entry_type: str = ENTRY_ISSUANCE,
    source_instance_id: str | None = None,
    world_id: str | None = None,
    character_id: str | None = None,
    dungeon_level: int | None = None,
    monster_type_id: str | None = None,
    monster_elo: float | None = None,
    chest_slot_id: str | None = None,
    metadata: dict | None = None,
    player=None,
) -> dict[str, Any]:
    """Credit PQG (amount must be >= 0)."""
    try:
        value = int(amount)
    except (TypeError, ValueError):
        value = 0
    if value < 0:
        return {
            'ok': False,
            'already_applied': False,
            'balance': get_balance(store, account_id),
            'event_id': None,
            'message': 'Credit amount must be non-negative.',
            'amount': value,
        }
    return _apply(
        store,
        account_id=account_id,
        amount=value,
        entry_type=entry_type,
        source=source,
        idempotency_key=idempotency_key,
        source_instance_id=source_instance_id,
        world_id=world_id,
        character_id=character_id,
        dungeon_level=dungeon_level,
        monster_type_id=monster_type_id,
        monster_elo=monster_elo,
        chest_slot_id=chest_slot_id,
        metadata=metadata,
        player=player,
    )


def debit(
    store,
    account_id: str,
    amount: int,
    *,
    source: str,
    idempotency_key: str,
    entry_type: str = ENTRY_SPEND,
    source_instance_id: str | None = None,
    world_id: str | None = None,
    character_id: str | None = None,
    dungeon_level: int | None = None,
    metadata: dict | None = None,
    player=None,
) -> dict[str, Any]:
    """Debit PQG (amount must be >= 0). Rejects if balance would go negative."""
    try:
        value = int(amount)
    except (TypeError, ValueError):
        value = 0
    if value < 0:
        return {
            'ok': False,
            'already_applied': False,
            'balance': get_balance(store, account_id),
            'event_id': None,
            'message': 'Debit amount must be non-negative.',
            'amount': value,
        }
    return _apply(
        store,
        account_id=account_id,
        amount=-value,
        entry_type=entry_type,
        source=source,
        idempotency_key=idempotency_key,
        source_instance_id=source_instance_id,
        world_id=world_id,
        character_id=character_id,
        dungeon_level=dungeon_level,
        metadata=metadata,
        player=player,
    )


def attach_account_to_player(store, player, *, starting_grant: bool = False) -> str:
    """
    Ensure ``player.account_id`` exists and the balance row is present.

    When ``starting_grant`` is True and the account is brand new, credit the
    player's current ``pqg`` (normally the starter 10) via the ledger.
    """
    if player is None:
        raise ValueError('player is required')
    existing = str(getattr(player, 'account_id', None) or '').strip()
    if existing:
        ensure_account(store, existing)
        sync_player_pqg(player, store)
        return existing

    account_id = ensure_account(store)
    player.account_id = account_id
    if starting_grant:
        starter = max(0, int(getattr(player, 'pqg', 0) or 0))
        if starter > 0:
            credit(
                store,
                account_id,
                starter,
                source=SOURCE_STARTING_GRANT,
                idempotency_key=f'starting:{account_id}',
                source_instance_id=account_id,
                character_id=getattr(player, 'id', None),
                metadata={'reason': 'new_character_starter'},
                player=player,
            )
        else:
            sync_player_pqg(player, store)
    else:
        sync_player_pqg(player, store)
    return account_id


def migrate_world_characters(store, world_id: str) -> dict[str, int]:
    """
    Create accounts for every character in ``world_id`` that lacks one, and
    seed balances from the character blob's ``pqg`` field.

    Idempotent: re-running skips characters that already have an account_id
    and skips seeding when the migration ledger key already exists.
    """
    stats = {'accounts_created': 0, 'seeded': 0, 'skipped': 0}
    if not world_id:
        return stats
    characters = store.load_characters(world_id, status=None) or {}
    for player_id, row in characters.items():
        data = dict(row.get('data') or {})
        account_id = str(row.get('account_id') or data.get('account_id') or '').strip()
        blob_pqg = 0
        try:
            blob_pqg = max(0, int(data.get('pqg', 0) or 0))
        except (TypeError, ValueError):
            blob_pqg = 0

        if not account_id:
            account_id = ensure_account(store)
            data['account_id'] = account_id
            store.save_character(
                world_id,
                player_id,
                data=data,
                status=row.get('status') or 'alive',
                death=row.get('death'),
                name_key=row.get('name_key'),
                password_hash=row.get('password_hash'),
                account_id=account_id,
            )
            stats['accounts_created'] += 1
        else:
            ensure_account(store, account_id)
            if not row.get('account_id'):
                store.save_character(
                    world_id,
                    player_id,
                    data=data,
                    status=row.get('status') or 'alive',
                    death=row.get('death'),
                    name_key=row.get('name_key'),
                    password_hash=row.get('password_hash'),
                    account_id=account_id,
                )

        seed = credit(
            store,
            account_id,
            blob_pqg,
            source=SOURCE_MIGRATION,
            entry_type=ENTRY_ADJUSTMENT,
            idempotency_key=f'migration:{world_id}:{player_id}',
            source_instance_id=player_id,
            world_id=world_id,
            character_id=player_id,
            metadata={'from_blob_pqg': blob_pqg},
        )
        if seed.get('already_applied'):
            stats['skipped'] += 1
        elif seed.get('ok') and blob_pqg > 0:
            stats['seeded'] += 1
        else:
            stats['skipped'] += 1
    return stats


def reconcile_account(store, account_id: str) -> dict[str, Any]:
    """Compare cached balance to SUM(ledger.amount). Returns drift info."""
    aid = str(account_id or '').strip()
    cached = get_balance(store, aid)
    summed = int(store.sum_pqg_ledger(aid) or 0)
    return {
        'account_id': aid,
        'cached_balance': cached,
        'ledger_sum': summed,
        'drift': cached - summed,
        'ok': cached == summed,
    }


class InsufficientPqgError(Exception):
    """Raised by the store when a debit would make the balance negative."""
