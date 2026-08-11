// main.js - Main game initialization
const Game = (function () {
    const KEY_TO_DIR = {
        w: 'w', a: 'a', s: 's', d: 'd',
        ArrowUp: 'w', ArrowLeft: 'a', ArrowDown: 's', ArrowRight: 'd',
    };

    /** Most-recently-pressed held direction is last. */
    const heldDirs = [];
    let holdRafId = null;

    function init() {
        UI.hideGameElements();
        SocketHandler.setupSocketEvents();
        setupEventListeners();
        window.socket = SocketHandler.socket;
    }

    function currentDir() {
        return heldDirs.length ? heldDirs[heldDirs.length - 1] : null;
    }

    function pressDir(dir) {
        const i = heldDirs.indexOf(dir);
        if (i >= 0) {
            heldDirs.splice(i, 1);
        }
        heldDirs.push(dir);
        tryMove();
        startHoldLoop();
    }

    function releaseDir(dir) {
        const i = heldDirs.indexOf(dir);
        if (i >= 0) {
            heldDirs.splice(i, 1);
        }
    }

    function clearHeld() {
        heldDirs.length = 0;
    }

    function startHoldLoop() {
        if (holdRafId !== null) {
            return;
        }
        holdRafId = requestAnimationFrame(function tick() {
            holdRafId = null;
            if (!currentDir()) {
                return;
            }
            tryMove();
            holdRafId = requestAnimationFrame(tick);
        });
    }

    function setupEventListeners() {
        document.querySelector('#player-login button').addEventListener('click', submitName);

        document.getElementById('player-name').addEventListener('keypress', function (e) {
            if (e.key === 'Enter') submitName();
        });

        document.addEventListener('keydown', function (e) {
            if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
                if (e.key === 'Escape') {
                    InspectUI.hide();
                }
                return;
            }
            const dir = KEY_TO_DIR[e.key];
            if (!dir) {
                return;
            }
            e.preventDefault();
            if (e.repeat) {
                return;
            }
            pressDir(dir);
        });

        document.addEventListener('keyup', function (e) {
            const dir = KEY_TO_DIR[e.key];
            if (dir) {
                releaseDir(dir);
            }
        });

        window.addEventListener('blur', clearHeld);

        document.querySelectorAll('.mobile-btn').forEach(btn => {
            const direction = btn.getAttribute('data-direction');
            if (!direction) {
                return;
            }
            const down = function (e) {
                e.preventDefault();
                if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
                    return;
                }
                pressDir(direction);
            };
            const up = function (e) {
                e.preventDefault();
                releaseDir(direction);
            };
            btn.addEventListener('pointerdown', down);
            btn.addEventListener('pointerup', up);
            btn.addEventListener('pointercancel', up);
            btn.addEventListener('pointerleave', up);
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
        const viewport = UI.prepareJoinViewport();
        SocketHandler.selectPlayerId(name, viewport);
    }

    function localPlayerId() {
        const el = document.getElementById('player-id');
        return el && el.value ? el.value : '';
    }

    function tryMove() {
        const direction = currentDir();
        if (!direction) {
            return;
        }
        if (typeof InspectUI !== 'undefined' && InspectUI.isOpen()) {
            return;
        }
        if (typeof PlayerPresentation !== 'undefined' && PlayerPresentation.beginLocalStep) {
            const id = localPlayerId();
            const t = PlayerPresentation.progress ? PlayerPresentation.progress(id) : 0;
            const pipelineAt = PlayerPresentation.PIPELINE_T || 0.85;
            const opts = (t >= pipelineAt) ? { pipeline: true } : {};
            if (!PlayerPresentation.beginLocalStep(id, opts)) {
                return;
            }
        }
        SocketHandler.sendMove(direction);
    }

    window.submitName = submitName;
    window.move = function (direction) {
        if (direction) {
            pressDir(direction);
        }
    };
    window.sendCombatAction = Combat.sendAction;

    return { init };
})();

document.addEventListener('DOMContentLoaded', Game.init);
