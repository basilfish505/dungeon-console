// main.js - Main game initialization
const Game = (function () {
    function init() {
        UI.hideGameElements();
        SocketHandler.setupSocketEvents();
        setupEventListeners();
        window.socket = SocketHandler.socket;
    }

    function setupEventListeners() {
        document.querySelector('#player-login button').addEventListener('click', submitName);

        document.getElementById('player-name').addEventListener('keypress', function (e) {
            if (e.key === 'Enter') submitName();
        });

        document.addEventListener('keydown', function (e) {
            if (['w', 'a', 's', 'd'].includes(e.key)) move(e.key);
        });

        document.querySelectorAll('.mobile-btn').forEach(btn => {
            const direction = btn.getAttribute('data-direction');
            if (direction) {
                btn.addEventListener('click', function () { move(direction); });
            }
        });

        document.querySelectorAll('#combat-controls button').forEach(btn => {
            btn.addEventListener('click', function () {
                Combat.sendAction(this.id.replace('-btn', ''));
            });
        });

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
        // Measure pane first, then join with that viewport so the first map is final size
        const viewport = UI.prepareJoinViewport();
        SocketHandler.selectPlayerId(name, viewport);
    }

    const move = Utils.throttle(function (direction) {
        SocketHandler.sendMove(direction);
    }, 100);

    window.submitName = submitName;
    window.move = move;
    window.sendCombatAction = Combat.sendAction;

    return { init };
})();

document.addEventListener('DOMContentLoaded', Game.init);
