/**
 * SiteSage Main Application Controller (Vanilla JavaScript)
 */

document.addEventListener('DOMContentLoaded', () => {
    // ── Elements ──────────────────────────────────────────────────────
    const searchForm = document.getElementById('search-form');
    const urlInput = document.getElementById('url-input');
    const questionInput = document.getElementById('question-input');
    const maxPagesInput = document.getElementById('max-pages-input');
    const maxPagesValue = document.getElementById('max-pages-value');
    const polishToggle = document.getElementById('polish-toggle');
    const searchBtn = document.getElementById('search-btn');

    const dashboardSection = document.getElementById('dashboard-section');
    const cancelBtn = document.getElementById('btn-cancel-search');
    const resultsSection = document.getElementById('results-section');
    const emptyStateSection = document.getElementById('empty-state-section');

    const historyDrawer = document.getElementById('history-drawer');
    const drawerBackdrop = document.getElementById('drawer-backdrop');
    const historyToggleBtn = document.getElementById('btn-toggle-history');
    const closeHistoryBtn = document.getElementById('btn-close-history');

    // ── Application State ─────────────────────────────────────────────
    let currentSessionId = null;
    let isSearching = false;
    const streamManager = new SearchStreamManager();

    // ── Presets ───────────────────────────────────────────────────────
    const presetButtons = document.querySelectorAll('.preset-pill');
    presetButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (isSearching) return;
            const targetUrl = btn.dataset.url;
            const targetQuestion = btn.dataset.question;
            const targetMax = btn.dataset.max || 10;

            if (targetUrl) urlInput.value = targetUrl;
            if (targetQuestion) questionInput.value = targetQuestion;
            if (targetMax && maxPagesInput) {
                maxPagesInput.value = targetMax;
                if (maxPagesValue) maxPagesValue.textContent = targetMax;
            }
            questionInput.focus();
        });
    });

    // ── Feed Accordion Toggle ────────────────────────────────────────
    const toggleFeedBtn = document.getElementById('btn-toggle-feed');
    const activityFeed = document.getElementById('dash-activity-feed');
    if (toggleFeedBtn && activityFeed) {
        toggleFeedBtn.addEventListener('click', () => {
            const isHidden = activityFeed.hidden;
            activityFeed.hidden = !isHidden;
            toggleFeedBtn.setAttribute('aria-expanded', isHidden ? 'true' : 'false');
            toggleFeedBtn.classList.toggle('active', isHidden);
            const icon = toggleFeedBtn.querySelector('.feed-toggle-icon');
            if (icon) icon.textContent = isHidden ? '▼' : '▶';
        });
    }

    // ── Max Pages Slider Binding ──────────────────────────────────────
    if (maxPagesInput && maxPagesValue) {
        maxPagesInput.addEventListener('input', (e) => {
            maxPagesValue.textContent = e.target.value;
        });
    }

    // ── History Drawer Toggle ─────────────────────────────────────────
    if (historyToggleBtn && historyDrawer) {
        historyToggleBtn.addEventListener('click', () => {
            historyDrawer.classList.toggle('open');
            if (historyDrawer.classList.contains('open')) {
                loadHistory();
            }
        });
    }

    if (closeHistoryBtn && historyDrawer) {
        closeHistoryBtn.addEventListener('click', () => {
            historyDrawer.classList.remove('open');
        });
    }

    if (drawerBackdrop && historyDrawer) {
        drawerBackdrop.addEventListener('click', () => {
            historyDrawer.classList.remove('open');
        });
    }

    // ── Load History Function ─────────────────────────────────────────
    async function loadHistory() {
        try {
            const sessions = await API.getSessions(25);
            UI.renderSessionHistory(sessions, async (selectedSession) => {
                historyDrawer.classList.remove('open');
                await loadPreviousSession(selectedSession.id);
            });
        } catch (err) {
            console.warn('Could not load sessions:', err);
        }
    }

    // Initial silent load of session history count
    API.getSessions(5).then(sessions => {
        const countBadge = document.getElementById('history-count-badge');
        if (countBadge && sessions.length > 0) {
            countBadge.textContent = sessions.length;
            countBadge.hidden = false;
        }
    }).catch(() => {});

    // ── Load a Previous Session ───────────────────────────────────────
    async function loadPreviousSession(sessionId) {
        if (isSearching) {
            UI.showToast('Please stop current search before viewing history.', 'warning');
            return;
        }

        try {
            UI.showToast('Loading saved search...', 'info', 1500);
            const status = await API.getStatus(sessionId);

            // Populate form inputs
            if (status.seed_url) urlInput.value = status.seed_url;
            if (status.question) questionInput.value = status.question;

            // Render dashboard summary
            dashboardSection.hidden = false;
            cancelBtn.hidden = true;
            emptyStateSection.hidden = true;
            UI.updateDashboard(status);

            // Fetch and render results if available
            const results = await API.getResults(sessionId);
            UI.renderResults(results);
            resultsSection.scrollIntoView({ behavior: 'smooth' });
        } catch (err) {
            UI.showToast(`Error opening session: ${err.message}`, 'error');
        }
    }

    // ── Form Submission ───────────────────────────────────────────────
    searchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (isSearching) return;

        let url = urlInput.value.trim();
        const question = questionInput.value.trim();
        const maxPages = parseInt(maxPagesInput.value, 10) || 15;
        const polish = polishToggle ? polishToggle.checked : false;

        // URL safety & normalization
        if (!url) {
            UI.showToast('Please provide a valid website URL.', 'warning');
            urlInput.focus();
            return;
        }

        if (!/^https?:\/\//i.test(url)) {
            url = 'https://' + url;
            urlInput.value = url;
        }

        if (question.length < 3) {
            UI.showToast('Please enter a question with at least 3 characters.', 'warning');
            questionInput.focus();
            return;
        }

        // Set search state
        setSearchingState(true);
        emptyStateSection.hidden = true;
        resultsSection.hidden = true;
        dashboardSection.hidden = false;
        cancelBtn.hidden = false;

        // Clear previous event logs
        const feed = document.getElementById('dash-activity-feed');
        if (feed) feed.innerHTML = '';

        UI.updateDashboard({
            stage: 'initialization',
            status: 'pending',
            pages_crawled: 0,
            pages_discovered: 0,
            pages_queued: 0,
            pages_failed: 0,
            max_pages: maxPages,
            current_url: url,
        });

        try {
            const startData = await API.startSearch(url, question, maxPages, polish);
            currentSessionId = startData.session_id;

            UI.appendEventLog('session_started', {
                stage: 'initialization',
                status: 'pending',
                message: `Session initialized for ${url}`,
            });

            // Connect to real-time SSE stream
            streamManager.connect(currentSessionId, {
                onEvent: (eventType, data) => {
                    UI.updateDashboard(data);
                    UI.appendEventLog(eventType, data);
                },
                onError: (err) => {
                    UI.showToast(err.message, 'warning');
                },
                onComplete: async ({ isSuccess, isCancelled, eventType, data }) => {
                    setSearchingState(false);
                    cancelBtn.hidden = true;

                    if (isCancelled) {
                        UI.showToast('Search was cancelled.', 'warning');
                        return;
                    }

                    if (!isSuccess) {
                        UI.showToast(data.message || 'Search encountered an issue.', 'error');
                        return;
                    }

                    // Retrieve final SearchResult
                    try {
                        UI.showToast('Retrieving verified evidence...', 'info', 1000);
                        const results = await API.getResults(currentSessionId, polish);
                        UI.renderResults(results);
                        resultsSection.scrollIntoView({ behavior: 'smooth' });
                    } catch (fetchErr) {
                        UI.showToast(`Error retrieving answer: ${fetchErr.message}`, 'error');
                    }
                }
            });

        } catch (err) {
            setSearchingState(false);
            cancelBtn.hidden = true;
            UI.showToast(err.message, 'error');
            UI.appendEventLog('pipeline_error', {
                stage: 'error',
                status: 'error',
                message: err.message,
            });
        }
    });

    // ── Cancel Search ─────────────────────────────────────────────────
    cancelBtn.addEventListener('click', async () => {
        if (!currentSessionId || !isSearching) return;

        cancelBtn.disabled = true;
        cancelBtn.textContent = 'Stopping...';

        try {
            await API.cancelSearch(currentSessionId);
            UI.showToast('Search cancellation requested...', 'info');
        } catch (err) {
            UI.showToast(`Failed to cancel: ${err.message}`, 'error');
            cancelBtn.disabled = false;
            cancelBtn.textContent = 'Stop Search';
        }
    });

    // ── UI State Helper ───────────────────────────────────────────────
    function setSearchingState(searching) {
        isSearching = searching;
        searchBtn.disabled = searching;
        searchBtn.innerHTML = searching 
            ? '<span class="spinner"></span> Searching...'
            : '<span class="icon">🔍</span> Search Website';

        cancelBtn.disabled = false;
        cancelBtn.textContent = 'Stop Search';

        if (searching) {
            dashboardSection.scrollIntoView({ behavior: 'smooth' });
        }
    }

    // ── Keyboard Shortcuts ────────────────────────────────────────────
    window.addEventListener('keydown', (e) => {
        // Ctrl+Enter or Cmd+Enter to submit
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            if (!isSearching && (document.activeElement === questionInput || document.activeElement === urlInput)) {
                searchForm.requestSubmit();
            }
        }
        // Escape to close history
        if (e.key === 'Escape') {
            if (historyDrawer && historyDrawer.classList.contains('open')) {
                historyDrawer.classList.remove('open');
            }
        }
    });
});
