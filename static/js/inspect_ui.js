// inspect_ui.js — modal for map inspect results (monster first; kind-dispatch ready)
const InspectUI = (function () {
    let overlayEl = null;
    let panelEl = null;
    let titleEl = null;
    let bodyEl = null;
    let open = false;
    let alertOpen = false;

    function ensureEls() {
        if (overlayEl) {
            return true;
        }
        overlayEl = document.getElementById('inspect-overlay');
        panelEl = document.getElementById('inspect-panel');
        titleEl = document.getElementById('inspect-title');
        bodyEl = document.getElementById('inspect-body');
        if (!overlayEl || !panelEl || !titleEl || !bodyEl) {
            return false;
        }
        const closeBtn = document.getElementById('inspect-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                hide();
            });
        }
        overlayEl.addEventListener('click', function (e) {
            if (e.target === overlayEl) {
                hide();
            }
        });
        // Stop map gestures from seeing pointer events on the panel
        panelEl.addEventListener('pointerdown', function (e) {
            e.stopPropagation();
        });
        return true;
    }

    function isOpen() {
        return open || alertOpen;
    }

    function escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text == null ? '' : String(text);
        return d.innerHTML;
    }

    function setCombatantHeading(data, fallbackName) {
        const name = data.name || fallbackName || 'Unknown';
        const level = data.level != null ? data.level : '?';
        const main = name + ' (Level ' + level + ')';
        let eloHtml = '';
        if (data.elo != null && data.elo !== '') {
            const elo = Math.round(Number(data.elo));
            if (!Number.isNaN(elo)) {
                let text = 'ELO RATING: ' + elo;
                if (data.elo_percentile != null && data.elo_percentile !== '') {
                    const pct = Number(data.elo_percentile);
                    if (!Number.isNaN(pct)) {
                        text += ' (' + pct.toFixed(1) + '%)';
                    }
                }
                eloHtml = '<span class="inspect-elo">' + escapeHtml(text) + '</span>';
            }
        }
        titleEl.innerHTML =
            '<span class="inspect-title-main">' + escapeHtml(main) + '</span>' +
            eloHtml;
    }

    function setMonsterHeading(data) {
        setCombatantHeading(data, 'Monster');
    }

    function renderAttrSection(data) {
        let html = '';
        const attrs = data.attributes || [];
        if (attrs.length) {
            html += '<h4 class="inspect-section">Attributes</h4>';
            attrs.forEach(function (row) {
                html += `<div class="inspect-row"><span class="inspect-label">${escapeHtml(row.label)}</span>` +
                    `<span class="inspect-value">${escapeHtml(row.value)}</span></div>`;
            });
        }
        return html;
    }

    function renderMonster(data) {
        if (!data) {
            return '';
        }
        let html = '';
        if (data.portrait) {
            html += `<div class="inspect-portrait-wrap"><img class="inspect-portrait" src="${escapeHtml(data.portrait)}" alt="${escapeHtml(data.name || 'Monster')}"></div>`;
        }
        if (data.description) {
            html += `<p class="inspect-desc">${escapeHtml(data.description)}</p>`;
        }
        html += `<div class="inspect-row"><span class="inspect-label">HP</span>` +
            `<span class="inspect-value">${escapeHtml(data.hp)} / ${escapeHtml(data.mhp)}</span></div>`;
        if (data.armour != null) {
            html += `<div class="inspect-row"><span class="inspect-label">Armour</span>` +
                `<span class="inspect-value">${escapeHtml(data.armour)}</span></div>`;
        }
        if (data.mean_damage != null) {
            html += `<div class="inspect-row"><span class="inspect-label">Mean Damage</span>` +
                `<span class="inspect-value">${escapeHtml(data.mean_damage)}</span></div>`;
        }
        html += renderAttrSection(data);

        const abilities = data.abilities || [];
        if (abilities.length) {
            html += '<h4 class="inspect-section">Abilities</h4>';
            abilities.forEach(function (ab) {
                html += `<div class="inspect-row"><span class="inspect-value">${escapeHtml(ab.name || ab.id)}</span></div>`;
            });
        }
        return html;
    }

    function renderPlayer(data) {
        if (!data) {
            return '';
        }
        let html = '';
        if (data.portrait) {
            html += `<div class="inspect-portrait-wrap"><img class="inspect-portrait" src="${escapeHtml(data.portrait)}" alt="${escapeHtml(data.name || 'Player')}"></div>`;
        }
        html += `<div class="inspect-row"><span class="inspect-label">HP</span>` +
            `<span class="inspect-value">${escapeHtml(data.hp)} / ${escapeHtml(data.mhp)}</span></div>`;
        if (data.mmp != null) {
            html += `<div class="inspect-row"><span class="inspect-label">MP</span>` +
                `<span class="inspect-value">${escapeHtml(data.mp)} / ${escapeHtml(data.mmp)}</span></div>`;
        }
        if (data.pqg != null) {
            html += `<div class="inspect-row"><span class="inspect-label">PQG</span>` +
                `<span class="inspect-value">${escapeHtml(data.pqg)}</span></div>`;
        }
        html += `<div class="inspect-row"><span class="inspect-label">Armour</span>` +
            `<span class="inspect-value">${escapeHtml(data.armour != null ? data.armour : 1)}</span></div>`;
        html += `<div class="inspect-row"><span class="inspect-label">Weapon</span>` +
            `<span class="inspect-value">${escapeHtml(data.weapon_name || 'Unarmed')}</span></div>`;
        html += `<div class="inspect-row"><span class="inspect-label">Mean Damage</span>` +
            `<span class="inspect-value">${escapeHtml(data.mean_damage != null ? data.mean_damage : '?')}</span></div>`;
        html += renderAttrSection(data);
        return html;
    }
    function buyItem(itemId) {
        if (!itemId || !window.socket) {
            return;
        }
        window.socket.emit('buy_item', { item_id: itemId });
    }

    function bindShopBuyClicks(container) {
        if (!container) {
            return;
        }
        container.querySelectorAll('.inspect-ware-buy[data-item-id]').forEach(function (row) {
            row.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                buyItem(row.getAttribute('data-item-id'));
            });
        });
    }

    function renderShop(data) {
        if (!data) {
            return '';
        }
        let html = '';
        if (data.portrait) {
            html += `<div class="inspect-portrait-wrap"><img class="inspect-portrait" src="${escapeHtml(data.portrait)}" alt="${escapeHtml(data.name || 'Shopkeeper')}"></div>`;
        }
        const greeting = data.greeting || data.description;
        if (greeting) {
            html += `<p class="inspect-desc">${escapeHtml(greeting)}</p>`;
        }
        const wares = data.wares || [];
        if (wares.length) {
            html += '<h4 class="inspect-section">For sale</h4>';
            html += '<p class="inspect-desc">Click an item to buy it.</p>';
            html += '<div class="inspect-wares">';
            wares.forEach(function (item) {
                const name = item.name || item.item_id || 'Item';
                const price = item.price_pqg != null ? item.price_pqg : 0;
                const img = item.image || '';
                const itemId = item.item_id || '';
                html += '<div class="inspect-ware inspect-ware-buy" role="button" tabindex="0" data-item-id="' +
                    escapeHtml(itemId) + '">';
                if (img) {
                    html += `<img class="inspect-ware-icon" src="${escapeHtml(img)}" alt="">`;
                }
                html += `<span class="inspect-ware-name">${escapeHtml(name)}</span>`;
                html += `<span class="inspect-ware-price">${escapeHtml(price)} pqg</span>`;
                html += '</div>';
            });
            html += '</div>';
        }
        return html;
    }

    function renderByKind(kind, data) {
        if (kind === 'monster') {
            return renderMonster(data);
        }
        if (kind === 'player') {
            return renderPlayer(data);
        }
        if (kind === 'shop' || kind === 'npc') {
            return renderShop(data);
        }
        return '<p class="inspect-desc">No details available.</p>';
    }

    function show(result) {
        if (!ensureEls() || !result || !result.ok) {
            return;
        }
        const data = result.data || {};
        const kind = result.kind || data.kind || 'unknown';
        if (kind === 'monster') {
            setMonsterHeading(data);
        } else if (kind === 'player') {
            setCombatantHeading(data, 'Player');
        } else {
            titleEl.textContent = data.name || kind;
        }
        bodyEl.innerHTML = renderByKind(kind, data);
        if (kind === 'shop' || kind === 'npc') {
            bindShopBuyClicks(bodyEl);
        }
        overlayEl.hidden = false;
        overlayEl.setAttribute('aria-hidden', 'false');
        open = true;
    }

    function hide() {
        if (!ensureEls()) {
            return;
        }
        overlayEl.hidden = true;
        overlayEl.setAttribute('aria-hidden', 'true');
        bodyEl.innerHTML = '';
        titleEl.textContent = '';
        titleEl.innerHTML = '';
        open = false;
    }

    let alertOverlayEl = null;
    let alertMessageEl = null;
    let alertOkBtn = null;
    let alertCancelBtn = null;
    let alertConfirmHandler = null;
    let alertCancelHandler = null;

    function ensureAlertEls() {
        if (alertOverlayEl) {
            return true;
        }
        alertOverlayEl = document.getElementById('shop-alert-overlay');
        alertMessageEl = document.getElementById('shop-alert-message');
        alertOkBtn = document.getElementById('shop-alert-ok');
        alertCancelBtn = document.getElementById('shop-alert-cancel');
        if (!alertOverlayEl || !alertMessageEl || !alertOkBtn) {
            return false;
        }
        alertOkBtn.addEventListener('click', function (e) {
            if (e) {
                e.preventDefault();
                e.stopPropagation();
            }
            const onConfirm = alertConfirmHandler;
            hideAlert();
            if (typeof onConfirm === 'function') {
                onConfirm();
            }
        });
        if (alertCancelBtn) {
            alertCancelBtn.addEventListener('click', function (e) {
                if (e) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                const onCancel = alertCancelHandler;
                hideAlert();
                if (typeof onCancel === 'function') {
                    onCancel();
                }
            });
        }
        alertOverlayEl.addEventListener('click', function (e) {
            if (e.target === alertOverlayEl) {
                const onCancel = alertCancelHandler;
                hideAlert();
                if (typeof onCancel === 'function') {
                    onCancel();
                }
            }
        });
        const panel = document.getElementById('shop-alert-panel');
        if (panel) {
            panel.addEventListener('pointerdown', function (e) {
                e.stopPropagation();
            });
        }
        return true;
    }

    function showAlert(message) {
        if (!ensureAlertEls()) {
            return;
        }
        const text = message == null ? '' : String(message);
        if (!text) {
            return;
        }
        alertConfirmHandler = null;
        alertCancelHandler = null;
        alertMessageEl.textContent = text;
        alertOkBtn.textContent = 'OK';
        if (alertCancelBtn) {
            alertCancelBtn.hidden = true;
        }
        alertOverlayEl.hidden = false;
        alertOverlayEl.setAttribute('aria-hidden', 'false');
        alertOpen = true;
        try {
            alertOkBtn.focus();
        } catch (err) {
            /* ignore */
        }
    }

    function showConfirm(message, opts) {
        if (!ensureAlertEls()) {
            return;
        }
        opts = opts || {};
        const text = message == null ? '' : String(message);
        if (!text) {
            return;
        }
        alertConfirmHandler = typeof opts.onConfirm === 'function' ? opts.onConfirm : null;
        alertCancelHandler = typeof opts.onCancel === 'function' ? opts.onCancel : null;
        alertMessageEl.textContent = text;
        alertOkBtn.textContent = opts.confirmLabel || 'Confirm';
        if (alertCancelBtn) {
            alertCancelBtn.hidden = false;
            alertCancelBtn.textContent = opts.cancelLabel || 'Cancel';
        }
        alertOverlayEl.hidden = false;
        alertOverlayEl.setAttribute('aria-hidden', 'false');
        alertOpen = true;
        try {
            alertOkBtn.focus();
        } catch (err) {
            /* ignore */
        }
    }

    function hideAlert() {
        if (!ensureAlertEls()) {
            return;
        }
        alertOverlayEl.hidden = true;
        alertOverlayEl.setAttribute('aria-hidden', 'true');
        alertMessageEl.textContent = '';
        alertConfirmHandler = null;
        alertCancelHandler = null;
        alertOkBtn.textContent = 'OK';
        if (alertCancelBtn) {
            alertCancelBtn.hidden = true;
            alertCancelBtn.textContent = 'Cancel';
        }
        alertOpen = false;
    }

    return { show, hide, isOpen, showAlert, showConfirm, hideAlert };
})();
