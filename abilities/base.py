"""Ability definition: one row of abilities.xlsx."""


class Ability:
    """Reusable ability definition identified by id.

    ``handler`` names an effect handler in abilities.handlers and ``params``
    are its parsed parameters. The ability is only ``functional`` when that
    handler has a code implementation; a spreadsheet row alone never makes an
    effect work.
    """

    def __init__(self, ability_id, name=None, description=None, handler=None,
                 params=None, source_row=None):
        self.id = str(ability_id)
        self.name = name if name is not None else self.id
        self.description = description if description else None
        self.handler = str(handler).strip() if handler else None
        self.params = dict(params or {})
        # Spreadsheet row the definition came from (for error messages).
        self.source_row = source_row

    @property
    def functional(self):
        from abilities.handlers import get_handler

        handler = get_handler(self.handler)
        return handler is not None and handler.implemented

    def __repr__(self):
        return f'Ability({self.id!r}, handler={self.handler!r}, params={self.params!r})'
