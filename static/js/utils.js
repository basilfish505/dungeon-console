// utils.js - Utility functions and helpers
const Utils = (function() {
    // Throttle function for movement
    function throttle(callback, delay) {
        let lastCall = 0;
        return function(...args) {
            const now = Date.now();
            if (now - lastCall >= delay) {
                lastCall = now;
                callback.apply(this, args);
            }
        };
    }
    
    // DOM element getter with caching
    const elements = {};
    function getElement(id) {
        if (!elements[id]) {
            elements[id] = document.getElementById(id);
        }
        return elements[id];
    }
    
    // Return public methods
    return {
        throttle,
        getElement
    };
})();