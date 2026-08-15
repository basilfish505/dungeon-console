"""Per-dungeon-level turn progress driven by player turn-consuming actions.

No real-world time: player actions accumulate until active-player threshold,
then one monster/world round runs on that level only.
"""

ACTIVE_PLAYER_ROUND_WINDOW = 3
LEVEL_TURNS_DEBUG = False


def _debug(msg):
    if LEVEL_TURNS_DEBUG:
        print(f"[level_turns] {msg}")


class LevelTurnState:
    """Independent turn/round counters for one dungeon level."""

    __slots__ = ('completed_round', 'turn_progress', 'last_action_round')

    def __init__(self):
        self.completed_round = 0
        self.turn_progress = 0
        # player_id -> completed_round when they last took a turn action on this level
        self.last_action_round = {}


def get_level_turn_state(game_state, level_number):
    """Lazy-create and return LevelTurnState for a dungeon level."""
    if not hasattr(game_state, 'level_turns') or game_state.level_turns is None:
        game_state.level_turns = {}
    state = game_state.level_turns.get(level_number)
    if state is None:
        state = LevelTurnState()
        game_state.level_turns[level_number] = state
    return state


def is_player_active_on_level(turn_state, player_id, player, level_number):
    """Active if on this level and acted within ACTIVE_PLAYER_ROUND_WINDOW completed rounds."""
    if player is None or player.dungeon_level != level_number:
        return False
    last = turn_state.last_action_round.get(player_id)
    if last is None:
        return False
    return (turn_state.completed_round - last) < ACTIVE_PLAYER_ROUND_WINDOW


def count_active_players(game_state, level_number, turn_state=None):
    """How many players currently count as active for the action threshold."""
    turn_state = turn_state or get_level_turn_state(game_state, level_number)
    n = 0
    for pid, player in game_state.players_on_level(level_number).items():
        if is_player_active_on_level(turn_state, pid, player, level_number):
            n += 1
    return n


def required_actions_for_level(game_state, level_number, turn_state=None):
    return max(1, count_active_players(game_state, level_number, turn_state))


def _rescale_progress(turn_state, old_required, new_required):
    """Preserve approximate progress fraction when the active-player threshold changes."""
    if old_required <= 0:
        old_required = 1
    if new_required <= 0:
        new_required = 1
    if old_required == new_required:
        return
    ratio = turn_state.turn_progress / float(old_required)
    if new_required <= 1:
        # Avoid a rebalance alone firing a round when required becomes 1.
        turn_state.turn_progress = 0
    else:
        scaled = int(round(ratio * new_required))
        turn_state.turn_progress = min(scaled, new_required - 1)


def _log_inactive_transitions(game_state, level_number, turn_state, before_active_ids):
    after = set()
    for pid, player in game_state.players_on_level(level_number).items():
        if is_player_active_on_level(turn_state, pid, player, level_number):
            after.add(pid)
    for pid in before_active_ids - after:
        _debug(f"Player {pid} marked inactive on level {level_number} "
               f"after {ACTIVE_PLAYER_ROUND_WINDOW} rounds without an action")
    for pid in after - before_active_ids:
        _debug(f"Player {pid} became active on level {level_number}")


def register_player_turn_action(game_state, player_id, combat_system=None, socketio=None):
    """
    Record a turn-consuming action for player_id on their current dungeon level.

    Returns True if at least one monster/world round was triggered.
    """
    # Import here to avoid circular imports at module load
    from monster_ai import run_monster_round_for_level

    player = game_state.players.get(player_id)
    if player is None:
        return False

    level_number = player.dungeon_level
    turn_state = get_level_turn_state(game_state, level_number)

    old_required = required_actions_for_level(game_state, level_number, turn_state)
    was_active = is_player_active_on_level(turn_state, player_id, player, level_number)

    turn_state.last_action_round[player_id] = turn_state.completed_round
    if not was_active:
        _debug(f"Player {player_id} became active on level {level_number}")

    new_required = required_actions_for_level(game_state, level_number, turn_state)
    if new_required != old_required:
        _rescale_progress(turn_state, old_required, new_required)

    turn_state.turn_progress += 1
    required = required_actions_for_level(game_state, level_number, turn_state)
    _debug(
        f"Player {player_id} performed turn action; "
        f"Level {level_number} progress: {turn_state.turn_progress}/{required}"
    )

    rounds_fired = 0
    while turn_state.turn_progress >= required:
        turn_state.turn_progress -= required

        before_active = {
            pid for pid, p in game_state.players_on_level(level_number).items()
            if is_player_active_on_level(turn_state, pid, p, level_number)
        }

        run_monster_round_for_level(
            game_state, level_number, combat_system, socketio,
            broadcast=False,
        )
        turn_state.completed_round += 1
        rounds_fired += 1
        _debug(
            f"Level {level_number} monster round {turn_state.completed_round} triggered"
        )

        _log_inactive_transitions(
            game_state, level_number, turn_state, before_active
        )
        required = required_actions_for_level(game_state, level_number, turn_state)

    return rounds_fired > 0
