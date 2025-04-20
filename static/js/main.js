// main.js - Main game initialization
const Game = (function() {
    // Initialize game
    function init() {
        // Hide game elements initially
        UI.hideGameElements();
        
        // Set up socket events
        SocketHandler.setupSocketEvents();
        
        // Set up UI event handlers
        setupEventListeners();
        
        // Make socket globally available
        window.socket = SocketHandler.socket;
    }
    
    // Set up event listeners
    function setupEventListeners() {
        // Join button click
        const joinBtn = document.querySelector('#player-login button');
        joinBtn.addEventListener('click', submitName);
        
        // Player name input Enter key
        const playerNameInput = document.getElementById('player-name');
        playerNameInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                submitName();
            }
        });
        
        // Movement keys
        document.addEventListener('keydown', function(e) {
            if (['w', 'a', 's', 'd'].includes(e.key)) {
                move(e.key);
            }
        });
        
        // Movement buttons
        const mobileBtns = document.querySelectorAll('.mobile-btn');
        mobileBtns.forEach(btn => {
            const direction = btn.getAttribute('data-direction');
            if (direction) {
                btn.addEventListener('click', function() {
                    move(direction);
                });
            }
        });
        
        // Combat buttons
        const combatBtns = document.querySelectorAll('#combat-controls button');
        combatBtns.forEach(btn => {
            btn.addEventListener('click', function() {
                const action = this.id.replace('-btn', '');
                Combat.sendAction(action);
            });
        });
    }
    
    // Submit player name
    function submitName() {
        const playerNameInput = document.getElementById('player-name');
        const name = playerNameInput.value.trim();
        if (name) {
            SocketHandler.selectPlayerId(name);
            UI.showGameElements();
        }
    }
    
    // Movement with throttling
    const move = Utils.throttle(function(direction) {
        SocketHandler.sendMove(direction);
    }, 100);
    
    // Expose necessary functions to global scope for HTML onclick attributes
    window.submitName = submitName;
    window.move = move;
    window.sendCombatAction = Combat.sendAction;
    
    // Return public API
    return {
        init
    };
})();

// Initialize the game when the DOM is loaded
document.addEventListener('DOMContentLoaded', Game.init);