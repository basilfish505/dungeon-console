// interaction_ui.js — player bump prompt + chat session
const InteractionUI = (function () {
    let promptOverlay = null;
    let promptPanel = null;
    let promptTitle = null;
    let promptMessage = null;
    let promptCountdown = null;
    let promptChoices = null;
    let chatOverlay = null;
    let chatPanel = null;
    let chatTitle = null;
    let chatLog = null;
    let chatInput = null;
    let chatSendBtn = null;
    let chatEndBtn = null;

    let promptOpen = false;
    let chatOpen = false;
    let currentInteractionId = null;
    let currentOtherId = null;
    let countdownTimer = null;
    let countdownRemaining = 0;
    let bound = false;
    let viewportBound = false;

    const CHOICE_LABELS = {
        attack: 'Attack',
        demand: 'Demand Goods',
        chat: 'Chat',
        leave: 'Leave',
    };

    function ensureEls() {
        if (promptOverlay && chatOverlay) {
            return true;
        }
        promptOverlay = document.getElementById('interaction-overlay');
        promptPanel = document.getElementById('interaction-panel');
        promptTitle = document.getElementById('interaction-title');
        promptMessage = document.getElementById('interaction-message');
        promptCountdown = document.getElementById('interaction-countdown');
        promptChoices = document.getElementById('interaction-choices');
        chatOverlay = document.getElementById('chat-overlay');
        chatPanel = document.getElementById('chat-panel');
        chatTitle = document.getElementById('chat-title');
        chatLog = document.getElementById('chat-log');
        chatInput = document.getElementById('chat-input');
        chatSendBtn = document.getElementById('chat-send');
        chatEndBtn = document.getElementById('chat-end');
        if (!promptOverlay || !chatOverlay) {
            return false;
        }
        if (!bound) {
            bound = true;
            if (promptPanel) {
                promptPanel.addEventListener('pointerdown', function (e) {
                    e.stopPropagation();
                });
            }
            if (chatPanel) {
                chatPanel.addEventListener('pointerdown', function (e) {
                    e.stopPropagation();
                });
            }
            if (chatSendBtn) {
                chatSendBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    sendChat();
                });
            }
            if (chatEndBtn) {
                chatEndBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    endChat();
                });
            }
            if (chatInput) {
                chatInput.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        sendChat();
                    }
                });
            }
        }
        return true;
    }

    function isOpen() {
        return promptOpen || chatOpen;
    }

    function stopCountdown() {
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }
        countdownRemaining = 0;
        if (promptCountdown) {
            promptCountdown.textContent = '';
        }
    }

    function startCountdown(seconds) {
        stopCountdown();
        if (!seconds || seconds <= 0 || !promptCountdown) {
            return;
        }
        countdownRemaining = seconds;
        promptCountdown.textContent = '(' + countdownRemaining + 's)';
        countdownTimer = setInterval(function () {
            countdownRemaining -= 1;
            if (countdownRemaining <= 0) {
                stopCountdown();
                return;
            }
            promptCountdown.textContent = '(' + countdownRemaining + 's)';
        }, 1000);
    }

    function hidePrompt() {
        stopCountdown();
        promptOpen = false;
        if (promptOverlay) {
            promptOverlay.hidden = true;
            promptOverlay.setAttribute('aria-hidden', 'true');
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
        }
    }

    /**
     * Pin the chat overlay to the visual viewport. On iOS the on-screen
     * keyboard shrinks the visual viewport without changing the layout
     * viewport, which otherwise clips the panel header (and End Chat).
     */
    function syncChatViewport() {
        if (!chatOverlay || !chatOpen) {
            return;
        }
        const vv = window.visualViewport;
        if (!vv) {
            return;
        }
        chatOverlay.style.top = vv.offsetTop + 'px';
        chatOverlay.style.left = vv.offsetLeft + 'px';
        chatOverlay.style.width = vv.width + 'px';
        chatOverlay.style.height = vv.height + 'px';
        chatOverlay.style.right = 'auto';
        chatOverlay.style.bottom = 'auto';
        chatOverlay.style.setProperty('--chat-vh', vv.height + 'px');
        if (chatLog) {
            chatLog.scrollTop = chatLog.scrollHeight;
        }
    }

    function clearChatViewport() {
        if (!chatOverlay) {
            return;
        }
        chatOverlay.style.top = '';
        chatOverlay.style.left = '';
        chatOverlay.style.width = '';
        chatOverlay.style.height = '';
        chatOverlay.style.right = '';
        chatOverlay.style.bottom = '';
        chatOverlay.style.removeProperty('--chat-vh');
    }

    function bindViewportSync() {
        const vv = window.visualViewport;
        if (!vv || viewportBound) {
            return;
        }
        viewportBound = true;
        vv.addEventListener('resize', syncChatViewport);
        vv.addEventListener('scroll', syncChatViewport);
    }

    function unbindViewportSync() {
        const vv = window.visualViewport;
        if (!vv || !viewportBound) {
            return;
        }
        viewportBound = false;
        vv.removeEventListener('resize', syncChatViewport);
        vv.removeEventListener('scroll', syncChatViewport);
    }

    function hideChat() {
        chatOpen = false;
        unbindViewportSync();
        clearChatViewport();
        if (chatOverlay) {
            chatOverlay.hidden = true;
            chatOverlay.setAttribute('aria-hidden', 'true');
        }
        if (chatLog) {
            chatLog.innerHTML = '';
        }
        if (chatInput) {
            chatInput.value = '';
        }
    }

    function hideAll() {
        hidePrompt();
        hideChat();
        currentInteractionId = null;
        currentOtherId = null;
    }

    function showPrompt(data) {
        if (!ensureEls()) {
            return;
        }
        hideChat();
        currentInteractionId = data.interaction_id || null;
        currentOtherId = data.other_id || null;
        const role = data.role || 'initiator';
        if (promptTitle) {
            promptTitle.textContent = role === 'responder'
                ? 'Respond to ' + (currentOtherId || 'player')
                : 'Encounter';
        }
        if (promptMessage) {
            promptMessage.textContent = data.message || '';
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
            const choices = data.choices || [];
            choices.forEach(function (choice) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'interaction-choice-btn';
                btn.dataset.choice = choice;
                btn.textContent = CHOICE_LABELS[choice] || choice;
                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    sendChoice(choice);
                });
                promptChoices.appendChild(btn);
            });
        }
        promptOpen = true;
        promptOverlay.hidden = false;
        promptOverlay.setAttribute('aria-hidden', 'false');
        startCountdown(data.timeout);
    }

    function showWaiting(data) {
        if (!ensureEls()) {
            return;
        }
        hideChat();
        currentInteractionId = data.interaction_id || null;
        currentOtherId = data.other_id || null;
        if (promptTitle) {
            promptTitle.textContent = 'Waiting';
        }
        if (promptMessage) {
            promptMessage.textContent = data.message || 'Waiting...';
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
        }
        promptOpen = true;
        promptOverlay.hidden = false;
        promptOverlay.setAttribute('aria-hidden', 'false');
        startCountdown(data.timeout);
    }

    function showChat(data) {
        if (!ensureEls()) {
            return;
        }
        hidePrompt();
        currentInteractionId = data.interaction_id || null;
        currentOtherId = data.other_id || null;
        if (chatTitle) {
            chatTitle.textContent = 'Chat with ' + (currentOtherId || 'player');
        }
        if (chatLog) {
            chatLog.innerHTML = '';
        }
        chatOpen = true;
        chatOverlay.hidden = false;
        chatOverlay.setAttribute('aria-hidden', 'false');
        bindViewportSync();
        syncChatViewport();
        if (chatInput) {
            chatInput.focus();
            // iOS reports the keyboard-shrunk viewport a beat after focus.
            setTimeout(syncChatViewport, 300);
        }
    }

    function appendChatMessage(data) {
        if (!ensureEls() || !chatLog) {
            return;
        }
        if (!chatOpen) {
            return;
        }
        const row = document.createElement('div');
        row.className = 'chat-line';
        const from = document.createElement('span');
        from.className = 'chat-from';
        from.textContent = (data.from || '?') + ': ';
        const text = document.createElement('span');
        text.className = 'chat-text';
        text.textContent = data.text || '';
        row.appendChild(from);
        row.appendChild(text);
        chatLog.appendChild(row);
        chatLog.scrollTop = chatLog.scrollHeight;
    }

    function sendChoice(choice) {
        if (!currentInteractionId) {
            return;
        }
        if (typeof SocketHandler !== 'undefined' && SocketHandler.sendInteractionChoice) {
            SocketHandler.sendInteractionChoice(currentInteractionId, choice);
        }
    }

    function sendChat() {
        if (!currentInteractionId || !chatInput) {
            return;
        }
        const text = chatInput.value;
        if (!text || !String(text).trim()) {
            return;
        }
        if (typeof SocketHandler !== 'undefined' && SocketHandler.sendChatMessage) {
            SocketHandler.sendChatMessage(currentInteractionId, text);
        }
        chatInput.value = '';
        chatInput.focus();
    }

    function endChat() {
        if (!currentInteractionId) {
            hideAll();
            return;
        }
        if (typeof SocketHandler !== 'undefined' && SocketHandler.endChat) {
            SocketHandler.endChat(currentInteractionId);
        }
    }

    function processUpdate(data) {
        if (!data || !data.type) {
            return;
        }
        switch (data.type) {
            case 'interaction_prompt':
                showPrompt(data);
                break;
            case 'interaction_waiting':
                showWaiting(data);
                break;
            case 'interaction_end':
                hideAll();
                break;
            case 'chat_start':
                showChat(data);
                break;
            case 'chat_message':
                appendChatMessage(data);
                break;
            case 'chat_end':
                hideAll();
                break;
            default:
                break;
        }
    }

    return {
        isOpen: isOpen,
        processUpdate: processUpdate,
        hide: hideAll,
    };
})();
