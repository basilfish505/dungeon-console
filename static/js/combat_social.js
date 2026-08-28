// combat_social.js — Alliance / Chat combat actions + social update handling
const CombatSocial = (function () {
    let socialRow = null;
    let allianceBtn = null;
    let chatBtn = null;
    let bound = false;
    let lastCombatants = [];
    let lastViewerId = null;

    function ensureEls() {
        if (!socialRow) {
            socialRow = document.getElementById('combat-social-controls');
        }
        if (!allianceBtn) {
            allianceBtn = document.getElementById('alliance-btn');
        }
        if (!chatBtn) {
            chatBtn = document.getElementById('chat-btn');
        }
        return !!(socialRow && allianceBtn && chatBtn);
    }

    function otherPlayers(combatants, viewerId) {
        return (combatants || []).filter(function (c) {
            return c && !c.is_monster && c.id && c.id !== viewerId;
        });
    }

    function setRowVisible(visible) {
        if (!ensureEls()) {
            return;
        }
        socialRow.hidden = !visible;
        socialRow.setAttribute('aria-hidden', visible ? 'false' : 'true');
    }

    function updateAvailability(combatants, viewerId) {
        lastCombatants = combatants || [];
        lastViewerId = viewerId || lastViewerId;
        const others = otherPlayers(lastCombatants, lastViewerId);
        setRowVisible(others.length > 0);
    }

    function emitSocial(action, payload) {
        if (typeof SocketHandler !== 'undefined' && SocketHandler.sendCombatSocial) {
            SocketHandler.sendCombatSocial(action, payload || {});
            return;
        }
        if (window.socket) {
            window.socket.emit('combat_social', Object.assign({ action: action }, payload || {}));
        }
    }

    function pickTargetsThen(action, title, message) {
        const others = otherPlayers(lastCombatants, lastViewerId);
        if (others.length === 0) {
            return;
        }
        if (others.length === 1) {
            emitSocial(action, { targets: [others[0].id] });
            return;
        }
        if (typeof InteractionUI === 'undefined' || !InteractionUI.showPicker) {
            // Fallback: invite everyone selected implicitly (all).
            emitSocial(action, {
                targets: others.map(function (o) { return o.id; }),
            });
            return;
        }
        InteractionUI.showPicker({
            title: title,
            message: message,
            options: others.map(function (o) {
                return { id: o.id, label: o.name || o.id };
            }),
            onConfirm: function (ids) {
                if (!ids || !ids.length) {
                    return;
                }
                emitSocial(action, { targets: ids });
            },
        });
    }

    function onAllianceClick(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        pickTargetsThen(
            'alliance_offer',
            'Offer Alliance',
            'Select one or more players to offer an alliance to.'
        );
    }

    function onChatClick(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        pickTargetsThen(
            'chat_invite',
            'Invite to Chat',
            'Select one or more players to invite to chat.'
        );
    }

    function bind() {
        if (bound || !ensureEls()) {
            return;
        }
        bound = true;
        allianceBtn.addEventListener('click', onAllianceClick);
        chatBtn.addEventListener('click', onChatClick);
    }

    function appendCombatLog(text) {
        if (typeof Combat !== 'undefined' && Combat.appendLog) {
            Combat.appendLog(text);
            return;
        }
        const log = document.getElementById('combat-log');
        if (!log || !text) {
            return;
        }
        const line = document.createElement('p');
        line.className = 'combat-log-line';
        line.textContent = text;
        log.appendChild(line);
        log.scrollTop = log.scrollHeight;
    }

    function processUpdate(data) {
        if (!data || !data.type) {
            return;
        }
        switch (data.type) {
            case 'alliance_offer':
                if (typeof InteractionUI !== 'undefined' && InteractionUI.showGenericPrompt) {
                    InteractionUI.showGenericPrompt({
                        id: data.offer_id,
                        title: 'Alliance Offer',
                        message: data.message || (
                            (data.from_id || 'A player') + ' offers you an alliance.'
                        ),
                        timeout: data.timeout || 10,
                        choices: [
                            { id: 'accept', label: 'Accept' },
                            { id: 'reject', label: 'Reject' },
                        ],
                        onChoice: function (choice) {
                            emitSocial('alliance_respond', {
                                offer_id: data.offer_id,
                                accept: choice === 'accept',
                            });
                        },
                    });
                }
                break;
            case 'alliance_formed':
                appendCombatLog(data.message || 'An alliance was formed.');
                break;
            case 'alliance_declined':
                appendCombatLog(data.message || 'Alliance offer declined.');
                break;
            case 'offer_cancelled':
                if (
                    typeof InteractionUI !== 'undefined'
                    && InteractionUI.hidePrompt
                    && data.kind === 'alliance'
                ) {
                    InteractionUI.hidePrompt();
                }
                if (data.reason === 'timeout') {
                    appendCombatLog('Alliance offer timed out.');
                }
                break;
            case 'social_notice':
                appendCombatLog(data.message || '');
                break;
            default:
                break;
        }
    }

    function hide() {
        setRowVisible(false);
        lastCombatants = [];
    }

    // Auto-bind when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bind);
    } else {
        bind();
    }

    return {
        updateAvailability: updateAvailability,
        processUpdate: processUpdate,
        hide: hide,
        bind: bind,
    };
})();
