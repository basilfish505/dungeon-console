// inventory_ui.js — 16-slot pack with a fixed info pane below the grid
const InventoryUI = (function () {
    const SLOT_COUNT = 16;
    let overlayEl = null;
    let gridEl = null;
    let detailEl = null;
    let titleEl = null;
    let context = 'exploration';
    let lastInventory = [];
    let selectable = false;
    let viewingItem = null;

    function cacheDom() {
        if (overlayEl) {
            return;
        }
        overlayEl = document.getElementById('inventory-overlay');
        gridEl = document.getElementById('inventory-grid');
        detailEl = document.getElementById('inventory-detail');
        titleEl = document.getElementById('inventory-title');
        const closeBtn = document.getElementById('inventory-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', close);
        }
        if (overlayEl) {
            overlayEl.addEventListener('click', function (e) {
                if (e.target === overlayEl) {
                    close();
                }
            });
        }
        const panelEl = document.getElementById('inventory-panel');
        if (panelEl) {
            panelEl.addEventListener('pointerdown', function (e) {
                e.stopPropagation();
            });
        }
    }

    function setInventory(items) {
        lastInventory = Array.isArray(items) ? items.slice() : [];
        if (overlayEl && !overlayEl.hidden) {
            if (viewingItem) {
                const still = lastInventory.find(function (row) {
                    return row && row.instance_id === viewingItem.instance_id;
                });
                viewingItem = still || null;
            }
            render();
        }
    }

    function getInventory() {
        return lastInventory;
    }

    function open(opts) {
        cacheDom();
        if (!overlayEl) {
            return;
        }
        opts = opts || {};
        context = opts.context || 'exploration';
        selectable = !!opts.selectable;
        viewingItem = null;
        if (Array.isArray(opts.items)) {
            lastInventory = opts.items.slice();
        }
        render();
        overlayEl.hidden = false;
        overlayEl.setAttribute('aria-hidden', 'false');
    }

    function close() {
        cacheDom();
        if (!overlayEl) {
            return;
        }
        overlayEl.hidden = true;
        overlayEl.setAttribute('aria-hidden', 'true');
        selectable = false;
        context = 'exploration';
        viewingItem = null;
        if (detailEl) {
            detailEl.innerHTML = '';
        }
    }

    function hide() {
        close();
    }

    function handleEscape() {
        if (viewingItem) {
            viewingItem = null;
            render();
            return;
        }
        close();
    }

    function isOpen() {
        cacheDom();
        return !!(overlayEl && !overlayEl.hidden);
    }

    function render() {
        cacheDom();
        if (titleEl) {
            titleEl.textContent = context === 'combat' ? 'Use Item' : 'Items';
        }
        renderGrid();
        renderDetail(viewingItem);
    }

    function renderGrid() {
        if (!gridEl) {
            return;
        }
        gridEl.innerHTML = '';
        for (let i = 0; i < SLOT_COUNT; i++) {
            const item = lastInventory[i] || null;
            const slot = document.createElement('button');
            slot.type = 'button';
            slot.className = 'inventory-slot';
            if (item) {
                slot.classList.add('inventory-slot-filled');
                if (viewingItem && viewingItem.instance_id === item.instance_id) {
                    slot.classList.add('inventory-slot-selected');
                }
                slot.textContent = item.name || item.type_id || 'Item';
                slot.setAttribute('aria-label', slot.textContent);
                slot.addEventListener('click', function () {
                    viewingItem = item;
                    render();
                });
            } else {
                slot.classList.add('inventory-slot-empty');
                slot.disabled = true;
                slot.setAttribute('aria-label', 'Empty slot');
                slot.textContent = '';
            }
            gridEl.appendChild(slot);
        }
    }

    function itemImageUrl(item) {
        if (typeof ItemAssets !== 'undefined') {
            return ItemAssets.getUrl(item.type_id, item.image);
        }
        return item.image || '/static/items/sprites/placeholder.png';
    }

    function renderDetail(item) {
        if (!detailEl) {
            return;
        }
        detailEl.innerHTML = '';

        const iconWrap = document.createElement('div');
        iconWrap.className = 'inventory-detail-icon-wrap';

        const meta = document.createElement('div');
        meta.className = 'inventory-detail-meta';

        if (!item) {
            const placeholder = document.createElement('div');
            placeholder.className = 'inventory-detail-icon inventory-detail-icon-empty';
            placeholder.setAttribute('aria-hidden', 'true');
            iconWrap.appendChild(placeholder);
            detailEl.appendChild(iconWrap);
            detailEl.appendChild(meta);
            return;
        }

        const img = document.createElement('img');
        img.className = 'inventory-detail-icon';
        img.alt = item.name || item.type_id || 'item';
        img.src = itemImageUrl(item);
        img.onerror = function () {
            img.onerror = null;
            img.src = (typeof ItemAssets !== 'undefined')
                ? ItemAssets.getPlaceholder()
                : '/static/items/sprites/placeholder.png';
        };
        iconWrap.appendChild(img);

        const name = document.createElement('div');
        name.className = 'inventory-detail-name';
        name.textContent = item.name || item.type_id || 'Unknown';

        const desc = document.createElement('p');
        desc.className = 'inventory-detail-desc';
        desc.textContent = item.description || '';

        const price = document.createElement('p');
        price.className = 'inventory-detail-price';
        const pqg = (item.price_pqg != null) ? item.price_pqg : 0;
        price.textContent = pqg + ' PQG';

        meta.appendChild(name);
        meta.appendChild(desc);
        meta.appendChild(price);

        if (selectable && context === 'combat') {
            const actions = document.createElement('div');
            actions.className = 'inventory-detail-actions';
            const useBtn = document.createElement('button');
            useBtn.type = 'button';
            useBtn.className = 'inventory-use-btn';
            useBtn.textContent = 'Use';
            useBtn.addEventListener('click', function () {
                useItem(item);
            });
            actions.appendChild(useBtn);
            meta.appendChild(actions);
        }

        detailEl.appendChild(iconWrap);
        detailEl.appendChild(meta);
    }

    function useItem(item) {
        if (!item || !item.instance_id) {
            return;
        }
        if (typeof window.socket === 'undefined' || !window.socket) {
            return;
        }
        window.socket.emit('use_item', {
            instance_id: item.instance_id,
        });
        close();
    }

    return {
        open: open,
        close: close,
        hide: hide,
        handleEscape: handleEscape,
        isOpen: isOpen,
        setInventory: setInventory,
        getInventory: getInventory,
    };
})();
