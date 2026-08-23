// main.js - Main game initialization
const Game = (function () {
    function init() {
        UI.hideGameElements();
        SocketHandler.setupSocketEvents();
        setupEventListeners();
        if (typeof MovementController !== 'undefined') {
            MovementController.bind();
        }
        window.socket = SocketHandler.socket;
    }

    function setupEventListeners() {
        document.querySelector('#player-login button').addEventListener('click', submitName);

        document.getElementById('player-name').addEventListener('keypress', function (e) {
            if (e.key === 'Enter') submitName();
        });

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

    function submitName() {
        const name = document.getElementById('player-name').value.trim();
        if (!name) return;
        Sound.warm(); // silent unlock + preload — no audible blip
        const viewport = UI.prepareJoinViewport();
        SocketHandler.selectPlayerId(name, viewport);
    }

    window.submitName = submitName;
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
