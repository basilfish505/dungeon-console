// spell_ui.js — known-spell cache + combat spell picker
const SpellUI = (function () {
    let knownSpells = [];

    function setSpells(spells) {
        knownSpells = Array.isArray(spells) ? spells.slice() : [];
    }

    function getSpells() {
        return knownSpells.slice();
    }

    function hasCastable() {
        return knownSpells.some(function (s) {
            return s && s.castable;
        });
    }

    function hasAny() {
        return knownSpells.length > 0;
    }

    /**
     * Open a single-choice spell picker.
     * opts: {onPick(spellId), onCancel()}
     */
    function open(opts) {
        opts = opts || {};
        if (typeof InteractionUI === 'undefined' || !InteractionUI.showGenericPrompt) {
            if (typeof opts.onCancel === 'function') {
                opts.onCancel();
            }
            return;
        }
        const list = knownSpells.slice();
        if (!list.length) {
            InteractionUI.showGenericPrompt({
                title: 'Spells',
                message: 'Thou knowest no spells.',
                choices: [{ id: 'ok', label: 'OK' }],
                onChoice: function () {
                    if (typeof opts.onCancel === 'function') {
                        opts.onCancel();
                    }
                },
            });
            return;
        }

        const choices = list.map(function (s) {
            const cost = (s.mp_cost != null) ? s.mp_cost : 0;
            let label = (s.name || s.spell_id || 'Spell') + ' (' + cost + ' MP)';
            if (!s.castable) {
                label += ' — not enough MP';
            }
            return {
                id: s.spell_id,
                label: label,
                castable: !!s.castable,
            };
        });

        InteractionUI.showGenericPrompt({
            title: 'Cast Spell',
            message: 'Choose a spell to cast.',
            choices: choices,
            onChoice: function (spellId) {
                const picked = list.find(function (s) {
                    return s && s.spell_id === spellId;
                });
                if (!picked || !picked.castable) {
                    InteractionUI.showGenericPrompt({
                        title: 'Spells',
                        message: 'Thou hast not enough MP.',
                        choices: [{ id: 'ok', label: 'OK' }],
                        onChoice: function () {
                            if (typeof opts.onCancel === 'function') {
                                opts.onCancel();
                            }
                        },
                    });
                    return;
                }
                if (typeof opts.onPick === 'function') {
                    opts.onPick(spellId);
                }
            },
        });
    }

    return {
        setSpells: setSpells,
        getSpells: getSpells,
        hasCastable: hasCastable,
        hasAny: hasAny,
        open: open,
    };
})();
