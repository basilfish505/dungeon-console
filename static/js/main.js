// main.js - Main game initialization
const Game = (function () {
    function init() {
        UI.hideGameElements();
        SocketHandler.setupSocketEvents();
        if (typeof Entry !== 'undefined' && Entry.init) {
            Entry.init();
        }
        setupEventListeners();
        if (typeof MovementController !== 'undefined') {
            MovementController.bind();
        }
        window.socket = SocketHandler.socket;
    }

    function setupEventListeners() {
        document.querySelectorAll('#combat-controls button').forEach(btn => {
            if (btn.id === 'map-peek-btn') {
                return;
            }
            btn.addEventListener('click', function () {
                Combat.sendAction(this.id.replace('-btn', ''));
            });
        });

        const itemsBtn = document.getElementById('pad-center-btn');
        if (itemsBtn) {
            itemsBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                if (typeof InventoryUI !== 'undefined') {
                    InventoryUI.open({
                        context: 'exploration',
                        selectable: false,
                        items: InventoryUI.getInventory(),
                    });
                }
            });
        }

        window.addEventListener('resize', function () {
            UI.requestMapUpdate('window-resize');
        });
        window.addEventListener('orientationchange', function () {
            setTimeout(UI.layoutForMobile, 100);
        });
        if (window.visualViewport) {
            window.visualViewport.addEventListener('resize', function () {
                UI.requestMapUpdate('visual-viewport');
            });
        }
    }

    window.move = function (direction) {
        if (!direction || typeof MovementController === 'undefined') {
            return;
        }
        MovementController.pressDir(direction);
        requestAnimationFrame(function () {
            MovementController.releaseDir(direction);
        });
    };
    window.sendCombatAction = Combat.sendAction;

    return { init };
})();

document.addEventListener('DOMContentLoaded', Game.init);
