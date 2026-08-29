// interaction_ui.js — player bump prompts + group chat sessions
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
    let chatRoster = null;
    let chatLog = null;
    let chatInput = null;
    let chatSendBtn = null;
    let chatEndBtn = null;

    let promptOpen = false;
    let chatOpen = false;
    // Several encounters can target one player at once, so payloads are held
    // by id and the most urgent one is drawn.
    const serverPrompts = new Map();
    let localPromptOpen = false;
    let renderedKey = null;
    let currentSessionId = null;
    let participants = [];
    let countdownTimer = null;
    let countdownRemaining = 0;
    let bound = false;
    let viewportBound = false;

    const CHOICE_LABELS = {
        attack: 'Attack',
        demand: 'Demand Goods',
        chat: 'Chat',
        leave: 'Leave',
        join: 'Join Battle',
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
        chatRoster = document.getElementById('chat-roster');
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
                    leaveChat();
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

    function hidePromptOverlay() {
        stopCountdown();
        promptOpen = false;
        renderedKey = null;
        if (promptOverlay) {
            promptOverlay.hidden = true;
            promptOverlay.setAttribute('aria-hidden', 'true');
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
            promptChoices.classList.remove('interaction-picker-mode');
        }
    }

    // --- prompt multiplexing ------------------------------------------

    /** An answerable prompt outranks a passive "waiting" notice. */
    function pickPrompt() {
        let best = null;
        serverPrompts.forEach(function (data) {
            if (data.type === 'interaction_prompt') {
                if (!best || best.type !== 'interaction_prompt') {
                    best = data;
                }
            } else if (!best) {
                best = data;
            }
        });
        return best;
    }

    function renderPrompt() {
        if (!ensureEls()) {
            return;
        }
        if (localPromptOpen) {
            return;
        }
        const next = pickPrompt();
        if (!next) {
            hidePromptOverlay();
            return;
        }
        const key = (next.interaction_id || '') + ':' + next.type;
        if (key === renderedKey) {
            return;
        }
        renderedKey = key;
        drawServerPrompt(next);
    }

    function drawServerPrompt(data) {
        const otherId = data.other_id || 'player';
        const isDecision = data.type === 'interaction_prompt';
        if (promptTitle) {
            if (data.title) {
                promptTitle.textContent = data.title;
            } else if (!isDecision) {
                promptTitle.textContent = 'Waiting';
            } else {
                promptTitle.textContent = (data.role === 'responder')
                    ? 'Respond to ' + otherId
                    : 'Encounter';
            }
        }
        if (promptMessage) {
            promptMessage.textContent = data.message || '';
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
            promptChoices.classList.remove('interaction-picker-mode');
            (data.choices || []).forEach(function (choice) {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'interaction-choice-btn';
                btn.dataset.choice = choice;
                btn.textContent = CHOICE_LABELS[choice] || choice;
                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    sendChoice(data.interaction_id, choice);
                });
                promptChoices.appendChild(btn);
            });
        }
        promptOpen = true;
        promptOverlay.hidden = false;
        promptOverlay.setAttribute('aria-hidden', 'false');
        startCountdown(data.timeout);
    }

    function sendChoice(interactionId, choice) {
        if (!interactionId) {
            return;
        }
        if (typeof SocketHandler !== 'undefined' && SocketHandler.sendInteractionChoice) {
            SocketHandler.sendInteractionChoice(interactionId, choice);
        }
    }

    // --- chat viewport --------------------------------------------------

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

    // --- chat session ---------------------------------------------------

    function hideChat() {
        chatOpen = false;
        currentSessionId = null;
        participants = [];
        unbindViewportSync();
        clearChatViewport();
        if (chatOverlay) {
            chatOverlay.hidden = true;
            chatOverlay.setAttribute('aria-hidden', 'true');
        }
        if (chatLog) {
            chatLog.innerHTML = '';
        }
        if (chatRoster) {
            chatRoster.textContent = '';
        }
        if (chatInput) {
            chatInput.value = '';
        }
    }

    function renderRoster() {
        if (chatRoster) {
            chatRoster.textContent = participants.join(', ');
        }
        if (chatTitle) {
            chatTitle.textContent = participants.length > 2
                ? 'Group Chat (' + participants.length + ')'
                : 'Chat';
        }
    }

    function appendSystemLine(text) {
        if (!chatLog) {
            return;
        }
        const row = document.createElement('div');
        row.className = 'chat-line chat-system';
        row.textContent = text;
        chatLog.appendChild(row);
        chatLog.scrollTop = chatLog.scrollHeight;
    }

    function appendMessageLine(from, text) {
        if (!chatLog) {
            return;
        }
        const row = document.createElement('div');
        row.className = 'chat-line';
        const fromEl = document.createElement('span');
        fromEl.className = 'chat-from';
        fromEl.textContent = (from || '?') + ': ';
        const textEl = document.createElement('span');
        textEl.className = 'chat-text';
        textEl.textContent = text || '';
        row.appendChild(fromEl);
        row.appendChild(textEl);
        chatLog.appendChild(row);
        chatLog.scrollTop = chatLog.scrollHeight;
    }

    function showChat(data) {
        if (!ensureEls()) {
            return;
        }
        currentSessionId = data.session_id || null;
        participants = (data.participants || []).slice();
        if (chatLog) {
            chatLog.innerHTML = '';
        }
        (data.history || []).forEach(function (entry) {
            appendMessageLine(entry.from, entry.text);
        });
        renderRoster();
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

    function sendChat() {
        if (!currentSessionId || !chatInput) {
            return;
        }
        const text = chatInput.value;
        if (!text || !String(text).trim()) {
            return;
        }
        if (typeof SocketHandler !== 'undefined' && SocketHandler.sendChatMessage) {
            SocketHandler.sendChatMessage(currentSessionId, text);
        }
        chatInput.value = '';
        chatInput.focus();
    }

    function leaveChat() {
        if (!currentSessionId) {
            hideChat();
            return;
        }
        if (typeof SocketHandler !== 'undefined' && SocketHandler.endChat) {
            SocketHandler.endChat(currentSessionId);
        }
    }

    function hideAll() {
        serverPrompts.clear();
        localPromptOpen = false;
        hidePromptOverlay();
        hideChat();
    }

    function processUpdate(data) {
        if (!data || !data.type) {
            return;
        }
        switch (data.type) {
            case 'interaction_prompt':
            case 'interaction_waiting':
                if (data.interaction_id) {
                    serverPrompts.set(data.interaction_id, data);
                    renderPrompt();
                }
                break;
            case 'interaction_end':
                if (data.interaction_id) {
                    serverPrompts.delete(data.interaction_id);
                    if (renderedKey
                        && renderedKey.indexOf(data.interaction_id + ':') === 0) {
                        renderedKey = null;
                        hidePromptOverlay();
                    }
                    renderPrompt();
                }
                break;
            case 'chat_start':
                showChat(data);
                break;
            case 'chat_message':
                if (chatOpen && data.session_id === currentSessionId) {
                    appendMessageLine(data.from, data.text);
                }
                break;
            case 'chat_join':
                if (chatOpen && data.session_id === currentSessionId) {
                    participants = (data.participants || []).slice();
                    renderRoster();
                    appendSystemLine((data.player_id || 'A player') + ' joined.');
                }
                break;
            case 'chat_leave':
                if (chatOpen && data.session_id === currentSessionId) {
                    participants = (data.participants || []).slice();
                    renderRoster();
                    appendSystemLine((data.player_id || 'A player') + ' left.');
                }
                break;
            case 'chat_end':
                if (!data.session_id || data.session_id === currentSessionId) {
                    hideChat();
                }
                break;
            default:
                break;
        }
    }

    // --- client-driven prompts (combat social actions) ------------------

    /**
     * Generic Accept/Reject (or similar) prompt reusing the interaction overlay.
     * opts: {title, message, choices:[{id,label}], timeout, onChoice(id)}
     */
    function showGenericPrompt(opts) {
        if (!ensureEls()) {
            return;
        }
        opts = opts || {};
        localPromptOpen = true;
        renderedKey = null;
        if (promptTitle) {
            promptTitle.textContent = opts.title || 'Decision';
        }
        if (promptMessage) {
            promptMessage.textContent = opts.message || '';
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
            promptChoices.classList.remove('interaction-picker-mode');
            const choices = opts.choices || [];
            choices.forEach(function (choice) {
                const id = typeof choice === 'string' ? choice : choice.id;
                const label = typeof choice === 'string'
                    ? (CHOICE_LABELS[choice] || choice)
                    : (choice.label || choice.id);
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'interaction-choice-btn';
                btn.dataset.choice = id;
                btn.textContent = label;
                btn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    closeLocalPrompt();
                    if (typeof opts.onChoice === 'function') {
                        opts.onChoice(id);
                    }
                });
                promptChoices.appendChild(btn);
            });
        }
        promptOpen = true;
        promptOverlay.hidden = false;
        promptOverlay.setAttribute('aria-hidden', 'false');
        startCountdown(opts.timeout);
    }

    /**
     * Multi-select recipient picker.
     * opts: {title, message, options:[{id,label}], onConfirm(ids), onCancel()}
     */
    function showPicker(opts) {
        if (!ensureEls()) {
            return;
        }
        opts = opts || {};
        localPromptOpen = true;
        renderedKey = null;
        if (promptTitle) {
            promptTitle.textContent = opts.title || 'Select';
        }
        if (promptMessage) {
            promptMessage.textContent = opts.message || '';
        }
        if (promptChoices) {
            promptChoices.innerHTML = '';
            promptChoices.classList.add('interaction-picker-mode');
            const list = document.createElement('div');
            list.className = 'interaction-picker-list';
            const selected = {};
            (opts.options || []).forEach(function (opt) {
                const row = document.createElement('button');
                row.type = 'button';
                row.className = 'interaction-picker-option';
                row.dataset.id = opt.id;
                const box = document.createElement('input');
                box.type = 'checkbox';
                box.tabIndex = -1;
                const label = document.createElement('span');
                label.textContent = opt.label || opt.id;
                row.appendChild(box);
                row.appendChild(label);
                row.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    selected[opt.id] = !selected[opt.id];
                    box.checked = !!selected[opt.id];
                    row.classList.toggle('selected', !!selected[opt.id]);
                });
                list.appendChild(row);
            });
            promptChoices.appendChild(list);

            const confirmBtn = document.createElement('button');
            confirmBtn.type = 'button';
            confirmBtn.className = 'interaction-choice-btn';
            confirmBtn.textContent = 'Confirm';
            confirmBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                const ids = Object.keys(selected).filter(function (k) {
                    return selected[k];
                });
                closeLocalPrompt();
                if (typeof opts.onConfirm === 'function') {
                    opts.onConfirm(ids);
                }
            });
            const cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'interaction-choice-btn';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                closeLocalPrompt();
                if (typeof opts.onCancel === 'function') {
                    opts.onCancel();
                }
            });
            promptChoices.appendChild(confirmBtn);
            promptChoices.appendChild(cancelBtn);
        }
        promptOpen = true;
        promptOverlay.hidden = false;
        promptOverlay.setAttribute('aria-hidden', 'false');
        stopCountdown();
    }

    /** Dismiss a client-driven prompt and fall back to any queued server one. */
    function closeLocalPrompt() {
        localPromptOpen = false;
        hidePromptOverlay();
        renderPrompt();
    }

    return {
        isOpen: isOpen,
        processUpdate: processUpdate,
        hide: hideAll,
        showGenericPrompt: showGenericPrompt,
        showPicker: showPicker,
        hidePrompt: closeLocalPrompt,
    };
})();
