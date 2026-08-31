// entry.js — NEW / RETURNING character entry flow
const Entry = (function () {
    const panels = {};
    let rememberedName = null;
    let rememberedToken = null;
    let acceptedStats = null;
    let busy = false;

    function $(id) {
        return document.getElementById(id);
    }

    function cachePanels() {
        document.querySelectorAll('.entry-panel').forEach(function (el) {
            panels[el.getAttribute('data-panel')] = el;
        });
    }

    function showPanel(name) {
        Object.keys(panels).forEach(function (key) {
            panels[key].hidden = key !== name;
        });
        const screen = $('entry-screen');
        if (screen) {
            screen.style.display = 'flex';
        }
    }

    function setError(id, message) {
        const el = $(id);
        if (!el) {
            return;
        }
        if (message) {
            el.textContent = message;
            el.hidden = false;
        } else {
            el.textContent = '';
            el.hidden = true;
        }
    }

    function setBusy(isBusy) {
        busy = !!isBusy;
        document.querySelectorAll('#entry-screen .entry-btn').forEach(function (btn) {
            btn.disabled = busy;
        });
    }

    function renderStats(rows) {
        const list = $('entry-stats-list');
        if (!list) {
            return;
        }
        list.innerHTML = '';
        (rows || []).forEach(function (row) {
            const label = document.createElement('span');
            label.className = 'entry-stat-label';
            label.textContent = row.label;
            const value = document.createElement('span');
            value.className = 'entry-stat-value';
            value.textContent = String(row.value);
            list.appendChild(label);
            list.appendChild(value);
        });
    }

    function updateRememberedUI() {
        const continueBtn = $('entry-continue-btn');
        const logoutBtn = $('entry-logout-btn');
        if (rememberedName && continueBtn) {
            continueBtn.textContent = 'CONTINUE AS ' + rememberedName.toUpperCase();
            continueBtn.hidden = false;
            if (logoutBtn) {
                logoutBtn.hidden = false;
            }
        } else {
            if (continueBtn) {
                continueBtn.hidden = true;
            }
            if (logoutBtn) {
                logoutBtn.hidden = true;
            }
        }
    }

    function setRemembered(info, token) {
        if (info && info.name) {
            rememberedName = info.name;
            rememberedToken = token || rememberedToken;
        } else {
            rememberedName = null;
            rememberedToken = null;
        }
        updateRememberedUI();
    }

    async function postJson(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: body ? JSON.stringify(body) : '{}',
        });
        let data = null;
        try {
            data = await response.json();
        } catch (err) {
            data = null;
        }
        return { response: response, data: data };
    }

    async function rollStats() {
        setError('entry-stats-error', '');
        setBusy(true);
        try {
            const result = await postJson('/api/character/roll', {});
            if (!result.data || !result.data.ok) {
                setError(
                    'entry-stats-error',
                    (result.data && result.data.error) || 'Could not roll stats.'
                );
                return;
            }
            acceptedStats = null;
            renderStats(result.data.rows || []);
        } catch (err) {
            setError('entry-stats-error', 'Could not reach the server.');
        } finally {
            setBusy(false);
        }
    }

    function enterGame(token, displayName) {
        if (!token) {
            return;
        }
        if (typeof Sound !== 'undefined' && Sound.warm) {
            Sound.warm();
        }
        const viewport = UI.prepareJoinViewport();
        if (typeof SocketHandler !== 'undefined' && SocketHandler.enterGame) {
            SocketHandler.enterGame(token, viewport, displayName);
        }
    }

    async function startNewCharacter() {
        acceptedStats = null;
        if ($('entry-create-name')) {
            $('entry-create-name').value = '';
        }
        if ($('entry-create-password')) {
            $('entry-create-password').value = '';
        }
        if ($('entry-create-password-confirm')) {
            $('entry-create-password-confirm').value = '';
        }
        setError('entry-stats-error', '');
        setError('entry-name-error', '');
        setError('entry-password-error', '');
        showPanel('stats');
        await rollStats();
    }

    function acceptStats() {
        // Server already holds the pending roll in the session cookie.
        acceptedStats = true;
        setError('entry-name-error', '');
        showPanel('name');
        const input = $('entry-create-name');
        if (input) {
            input.focus();
        }
    }

    function goPassword() {
        const name = ($('entry-create-name').value || '').trim();
        if (!name) {
            setError('entry-name-error', 'Choose a character name.');
            return;
        }
        setError('entry-name-error', '');
        setError('entry-password-error', '');
        showPanel('password');
        const input = $('entry-create-password');
        if (input) {
            input.focus();
        }
    }

    async function createCharacter() {
        const name = ($('entry-create-name').value || '').trim();
        const password = $('entry-create-password').value || '';
        const confirm = $('entry-create-password-confirm').value || '';
        setError('entry-password-error', '');
        if (password !== confirm) {
            setError('entry-password-error', 'Passwords do not match.');
            return;
        }
        setBusy(true);
        try {
            const result = await postJson('/api/character/create', {
                name: name,
                password: password,
                password_confirm: confirm,
            });
            if (!result.data || !result.data.ok) {
                const err = (result.data && result.data.error) || 'Could not create character.';
                if (/name/i.test(err) && /unavail|exist|taken|choose|letter/i.test(err)) {
                    setError('entry-name-error', err);
                    showPanel('name');
                } else {
                    setError('entry-password-error', err);
                }
                return;
            }
            setRemembered({ name: result.data.name }, result.data.token);
            enterGame(result.data.token, result.data.name);
        } catch (err) {
            setError('entry-password-error', 'Could not reach the server.');
        } finally {
            setBusy(false);
        }
    }

    function showLogin() {
        setError('entry-login-error', '');
        if ($('entry-login-name')) {
            $('entry-login-name').value = '';
        }
        if ($('entry-login-password')) {
            $('entry-login-password').value = '';
        }
        showPanel('login');
        const input = $('entry-login-name');
        if (input) {
            input.focus();
        }
    }

    async function loadCharacter() {
        const name = ($('entry-login-name').value || '').trim();
        const password = $('entry-login-password').value || '';
        setError('entry-login-error', '');
        setBusy(true);
        try {
            const result = await postJson('/api/character/login', {
                name: name,
                password: password,
            });
            if (!result.data || !result.data.ok) {
                setError(
                    'entry-login-error',
                    (result.data && result.data.error) ||
                        'Incorrect character name or password.'
                );
                return;
            }
            setRemembered({ name: result.data.name }, result.data.token);
            enterGame(result.data.token, result.data.name);
        } catch (err) {
            setError('entry-login-error', 'Could not reach the server.');
        } finally {
            setBusy(false);
        }
    }

    async function continueAs() {
        if (!rememberedToken) {
            // Refresh token from the session endpoint.
            try {
                const response = await fetch('/api/session', {
                    credentials: 'same-origin',
                });
                const data = await response.json();
                if (data && data.remembered && data.token) {
                    setRemembered(data.remembered, data.token);
                }
            } catch (err) {
                /* fall through */
            }
        }
        if (!rememberedToken) {
            showLogin();
            return;
        }
        enterGame(rememberedToken, rememberedName);
    }

    async function logout() {
        setBusy(true);
        try {
            await postJson('/api/logout', {});
        } catch (err) {
            /* ignore */
        }
        setRemembered(null, null);
        if (typeof SocketHandler !== 'undefined' && SocketHandler.clearJoinedSession) {
            SocketHandler.clearJoinedSession();
        }
        setBusy(false);
        showChoice();
    }

    function showChoice() {
        setError('entry-login-error', '');
        setError('entry-stats-error', '');
        setError('entry-name-error', '');
        setError('entry-password-error', '');
        updateRememberedUI();
        showPanel('choice');
    }

    function bind() {
        cachePanels();
        $('entry-new-btn').addEventListener('click', function () {
            if (!busy) {
                startNewCharacter();
            }
        });
        $('entry-return-btn').addEventListener('click', function () {
            if (!busy) {
                showLogin();
            }
        });
        $('entry-continue-btn').addEventListener('click', function () {
            if (!busy) {
                continueAs();
            }
        });
        $('entry-logout-btn').addEventListener('click', function () {
            if (!busy) {
                logout();
            }
        });
        $('entry-shuffle-btn').addEventListener('click', function () {
            if (!busy) {
                rollStats();
            }
        });
        $('entry-accept-btn').addEventListener('click', function () {
            if (!busy) {
                acceptStats();
            }
        });
        $('entry-stats-back-btn').addEventListener('click', function () {
            if (!busy) {
                showChoice();
            }
        });
        $('entry-name-back-btn').addEventListener('click', function () {
            if (!busy) {
                showPanel('stats');
            }
        });
        $('entry-name-next-btn').addEventListener('click', function () {
            if (!busy) {
                goPassword();
            }
        });
        $('entry-password-back-btn').addEventListener('click', function () {
            if (!busy) {
                showPanel('name');
            }
        });
        $('entry-create-btn').addEventListener('click', function () {
            if (!busy) {
                createCharacter();
            }
        });
        $('entry-login-back-btn').addEventListener('click', function () {
            if (!busy) {
                showChoice();
            }
        });
        $('entry-load-btn').addEventListener('click', function () {
            if (!busy) {
                loadCharacter();
            }
        });

        $('entry-create-name').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !busy) {
                e.preventDefault();
                goPassword();
            }
        });
        $('entry-create-password-confirm').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !busy) {
                e.preventDefault();
                createCharacter();
            }
        });
        $('entry-login-password').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !busy) {
                e.preventDefault();
                loadCharacter();
            }
        });
    }

    function init() {
        bind();
        showChoice();
    }

    return {
        init: init,
        showChoice: showChoice,
        setRemembered: setRemembered,
        logout: logout,
    };
})();
