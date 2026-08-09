"""Ability definition stub (no execute / combat hooks yet)."""


class Ability:
    """Reusable ability definition identified by id. Logic comes later."""

    def __init__(self, ability_id, name=None):
        self.id = str(ability_id)
        self.name = name if name is not None else self.id
