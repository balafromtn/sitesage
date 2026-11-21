/**
 * SiteSage UI Renderer & DOM Controller (Vanilla JavaScript)
 */

const UI = {
    // ── Toast Notifications ───────────────────────────────────────────
    showToast(message, type = 'info', duration = 3500) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        let icon = 'ℹ️';
        if (type === 'success') icon = '✓';
        if (type === 'error') icon = '✕';
        if (type === 'warning') icon = '⚠';

        toast.innerHTML = `
            <span class="toast-icon">${icon}</span>
            <span class="toast-message">${UI.escapeHtml(message)}</span>
        `;

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => toast.classList.add('visible'));

        setTimeout(() => {
            toast.classList.remove('visible');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    // ── Stage & Progress Helper ───────────────────────────────────────
    getStageLabel(stage, status) {
        if (status === 'cancelled') return { label: 'Cancelled', class: 'stage-cancelled' };
        if (status === 'error') return { label: 'Failed', class: 'stage-error' };

        const map = {
            'initialization': { label: 'Initializing', class: 'stage-init' },
            'crawling': { label: 'Crawling Website', class: 'stage-crawl' },
            'indexing': { label: 'Indexing Passages', class: 'stage-index' },
            'retrieval': { label: 'Ranking & Decomposing', class: 'stage-retrieval' },
            'extracting': { label: 'Synthesizing Evidence', class: 'stage-extract' },
            'polishing': { label: 'Polishing Readability', class: 'stage-polish' },
            'completed': { label: 'Search Complete', class: 'stage-done' },
        };
        return map[stage] || { label: stage || 'Processing', class: 'stage-active' };
    },

    estimateProgressPercent(stage, status, pagesCrawled = 0, maxPages = 30) {
        if (status === 'done' || stage === 'completed') return 100;
        if (status === 'cancelled' || status === 'error') return 100;

        const crawlRatio = maxPages > 0 ? Math.min(pagesCrawled / maxPages, 1.0) : 0;

        switch (stage) {
            case 'initialization':
                return 5;
            case 'crawling':
                // Crawling takes from 5% to 60%
                return Math.round(5 + (crawlRatio * 55));
            case 'indexing':
                return 70;
            case 'retrieval':
                return 80;
            case 'extracting':
                return 90;
            case 'polishing':
                return 95;
            default:
                return 15;
        }
    },

    // ── Live Crawl Dashboard ──────────────────────────────────────────
    updateDashboard(data) {
        const stagePill = document.getElementById('dash-stage-pill');
        const progressBar = document.getElementById('dash-progress-fill');
        const progressPercent = document.getElementById('dash-progress-percent');
        const countCrawled = document.getElementById('count-crawled');
        const countDiscovered = document.getElementById('count-discovered');
        const countQueued = document.getElementById('count-queued');
        const countFailed = document.getElementById('count-failed');
        const currentUrlText = document.getElementById('dash-current-url');

        const stageInfo = UI.getStageLabel(data.stage, data.status);
        if (stagePill) {
            stagePill.textContent = stageInfo.label;
            stagePill.className = `status-pill ${stageInfo.class}`;
        }

        const percent = UI.estimateProgressPercent(
            data.stage,
            data.status,
            data.pages_crawled,
            data.max_pages
        );

        if (progressBar) progressBar.style.width = `${percent}%`;
        if (progressPercent) progressPercent.textContent = `${percent}%`;

        if (countCrawled) countCrawled.textContent = `${data.pages_crawled || 0} / ${data.max_pages || 30}`;
        if (countDiscovered) countDiscovered.textContent = data.pages_discovered || 0;
        if (countQueued) countQueued.textContent = data.pages_queued || 0;
        if (countFailed) countFailed.textContent = data.pages_failed || 0;

        if (currentUrlText) {
            currentUrlText.textContent = data.current_url || 'Analyzing links and content...';
        }
    },

    appendEventLog(eventType, data) {
        const feed = document.getElementById('dash-activity-feed');
        if (!feed) return;

        const item = document.createElement('div');
        item.className = 'feed-item';

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const stageBadge = UI.getStageLabel(data.stage, data.status).label;

        let icon = '•';
        if (eventType === 'page_crawled') icon = '📄';
        if (eventType === 'page_discovered') icon = '🔗';
        if (eventType === 'indexing_completed') icon = '⚡';
        if (eventType === 'evidence_found') icon = '🎯';
        if (eventType === 'answer_generated') icon = '✨';
        if (eventType === 'pipeline_completed') icon = '✓';
        if (eventType === 'session_cancelled') icon = '⏹';
        if (eventType === 'pipeline_error' || eventType === 'page_failed') icon = '⚠';

        item.innerHTML = `
            <span class="feed-time">${time}</span>
            <span class="feed-icon">${icon}</span>
            <span class="feed-msg">
                <strong>[${UI.escapeHtml(stageBadge)}]</strong> ${UI.escapeHtml(data.message || eventType)}
            </span>
        `;

        feed.appendChild(item);
        feed.scrollTop = feed.scrollHeight;
    },

    // ── Search Results Presentation ───────────────────────────────────
    renderResults(result) {
        const container = document.getElementById('results-section');
        if (!container) return;

        container.hidden = false;
        container.innerHTML = '';

        // 1. Primary Answer Header & Card
        const answerCard = document.createElement('div');
        answerCard.className = 'answer-card card';

        const polishBadge = result.ai_polished
            ? `<span class="badge badge-ai" title="Organized for readability with strict factual boundaries">✨ AI Polished</span>`
            : `<span class="badge badge-det" title="Extracted directly from website evidence with zero external additions">🔒 Verified Deterministic</span>`;

        const pagesCrawledText = `${result.pages_crawled || 0} page${result.pages_crawled === 1 ? '' : 's'} crawled`;

        answerCard.innerHTML = `
            <div class="answer-header">
                <div class="answer-title-group">
                    <h2 class="section-title">Evidence-Supported Answer</h2>
                    <div class="badge-group">
                        ${polishBadge}
                        <span class="badge badge-meta">${pagesCrawledText}</span>
                    </div>
                </div>
                <button class="btn btn-secondary btn-sm" id="btn-copy-answer">
                    <span class="icon">📋</span> Copy Answer
                </button>
            </div>
            <div class="answer-body markdown-content" id="answer-text-content">
                ${UI.formatMarkdown(result.answer || 'No direct answer could be extracted from the crawled pages.')}
            </div>
        `;
        container.appendChild(answerCard);

        // Bind copy button
        const copyBtn = answerCard.querySelector('#btn-copy-answer');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(result.answer || '')
                    .then(() => {
                        UI.showToast('Answer copied to clipboard!', 'success');
                        copyBtn.innerHTML = '<span class="icon">✓</span> Copied!';
                        setTimeout(() => {
                            copyBtn.innerHTML = '<span class="icon">📋</span> Copy Answer';
                        }, 2000);
                    })
                    .catch(() => UI.showToast('Could not copy to clipboard', 'error'));
            });
        }

        // 2. Missing Aspects Notice (if any)
        if (result.missing_aspects && result.missing_aspects.length > 0) {
            const missingAlert = document.createElement('div');
            missingAlert.className = 'alert alert-warning';
            missingAlert.innerHTML = `
                <div class="alert-header">
                    <span class="alert-icon">⚠</span>
                    <strong>Information Gap Detected</strong>
                </div>
                <p>The crawled website pages did not contain sufficient evidence to answer these specific parts of your inquiry:</p>
                <ul>
                    ${result.missing_aspects.map(a => `<li><strong>${UI.escapeHtml(a)}</strong></li>`).join('')}
                </ul>
            `;
            container.appendChild(missingAlert);
        }

        // 3. Contradiction Warnings (if any)
        if (result.conflicts && result.conflicts.length > 0) {
            const conflictAlert = document.createElement('div');
            conflictAlert.className = 'alert alert-danger';
            conflictAlert.innerHTML = `
                <div class="alert-header">
                    <span class="alert-icon">⚡</span>
                    <strong>Conflicting Evidence Found Across Pages</strong>
                </div>
                <p>Different pages on this website state conflicting information:</p>
                ${result.conflicts.map(c => `
                    <div class="conflict-item">
                        <div class="conflict-aspect">Aspect: <em>${UI.escapeHtml(c.aspect)}</em></div>
                        <ul class="conflict-quotes">
                            ${(c.conflicting_statements || []).map(s => `<li>"${UI.escapeHtml(s)}"</li>`).join('')}
                        </ul>
                        ${c.explanation ? `<div class="conflict-notes">${UI.escapeHtml(c.explanation)}</div>` : ''}
                    </div>
                `).join('')}
            `;
            container.appendChild(conflictAlert);
        }

        // 4. Claims & Citations Card
        if (result.claims && result.claims.length > 0) {
            const claimsCard = document.createElement('div');
            claimsCard.className = 'claims-card card';
            claimsCard.innerHTML = `
                <h3 class="section-subtitle">
                    Verified Claims & Exact Source Quotes (${result.claims.length})
                </h3>
                <div class="claims-list">
                    ${result.claims.map((claim, idx) => UI.renderClaimItem(claim, idx)).join('')}
                </div>
            `;
            container.appendChild(claimsCard);
        }

        // 5. Search Transparency Section
        const transparencyCard = document.createElement('div');
        transparencyCard.className = 'transparency-card card';
        transparencyCard.innerHTML = `
            <div class="accordion-header" id="transparency-toggle">
                <div class="accordion-title">
                    <span class="icon">🔍</span>
                    <h3>Search Transparency & BM25 Ranking Explainability</h3>
                </div>
                <span class="accordion-chevron">▼</span>
            </div>
            <div class="accordion-content" id="transparency-content">
                ${UI.renderTransparencyDetails(result)}
            </div>
        `;
        container.appendChild(transparencyCard);

        // Accordion toggle
        const toggle = transparencyCard.querySelector('#transparency-toggle');
        const content = transparencyCard.querySelector('#transparency-content');
        if (toggle && content) {
            toggle.addEventListener('click', () => {
                const isExpanded = content.classList.toggle('expanded');
                toggle.classList.toggle('active', isExpanded);
                const chevron = toggle.querySelector('.accordion-chevron');
                if (chevron) chevron.textContent = isExpanded ? '▲' : '▼';
            });
        }
    },

    renderClaimItem(c, index) {
        const confPercent = Math.round((c.confidence || 0) * 100);
        let confColor = '#10b981'; // Green
        if (confPercent < 60) confColor = '#f59e0b'; // Amber
        if (confPercent < 40) confColor = '#ef4444'; // Red

        const sourcesHtml = (c.sources || []).map(s => {
            const urlObj = new URL(s.page_url, window.location.origin);
            const pathDisplay = urlObj.pathname.length > 30 
                ? urlObj.pathname.substring(0, 27) + '...' 
                : urlObj.pathname || '/';

            return `
                <div class="source-ref-item">
                    <div class="source-meta-row">
                        <span class="source-badge">Source ${s.passage_id ? '#' + s.passage_id : ''}</span>
                        ${s.section_heading ? `<span class="heading-badge">§ ${UI.escapeHtml(s.section_heading)}</span>` : ''}
                        <a href="${UI.escapeHtml(s.page_url)}" target="_blank" rel="noopener noreferrer" class="source-url-link">
                            ${UI.escapeHtml(pathDisplay)} ↗
                        </a>
                    </div>
                    ${s.exact_quote ? `
                        <blockquote class="exact-quote">
                            "${UI.escapeHtml(s.exact_quote)}"
                        </blockquote>
                    ` : ''}
                </div>
            `;
        }).join('');

        return `
            <div class="claim-item">
                <div class="claim-header">
                    <span class="claim-index">#${index + 1}</span>
                    <div class="claim-text">
                        <strong>${UI.escapeHtml(c.claim)}</strong>
                        ${c.aspect ? `<div class="claim-aspect-tag">Aspect: ${UI.escapeHtml(c.aspect)}</div>` : ''}
                    </div>
                    <div class="confidence-pill" style="border-color: ${confColor}; color: ${confColor};" title="Calculated evidence confidence score">
                        ${confPercent}% Conf.
                    </div>
                </div>
                <div class="claim-sources-container">
                    ${sourcesHtml}
                </div>
            </div>
        `;
    },

    renderTransparencyDetails(result) {
        // Question Aspects Breakdown
        const aspectsHtml = (result.question_aspects || []).map(a => `
            <div class="aspect-chip-card">
                <div class="aspect-title">🎯 ${UI.escapeHtml(a.aspect)}</div>
                <div class="aspect-keywords">
                    ${(a.keywords || []).map(k => `<span class="keyword-pill">${UI.escapeHtml(k)}</span>`).join('')}
                </div>
            </div>
        `).join('') || '<p class="text-muted">Single unified search intent.</p>';

        // Ranked Passages / BM25 Explanations
        const passages = (result.evidence || []).concat(result.alternative_sources || []);
        
        let passagesHtml = '';
        if (passages.length > 0) {
            passagesHtml = `
                <div class="table-responsive">
                    <table class="explain-table">
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Source URL & Heading</th>
                                <th>Base BM25</th>
                                <th>Title Boost</th>
                                <th>Heading Boost</th>
                                <th>Position Boost</th>
                                <th>Depth Penalty</th>
                                <th>Total Score</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${passages.slice(0, 10).map((sp, idx) => {
                                const p = sp.passage || {};
                                const sb = sp.score_breakdown || {};
                                const urlObj = new URL(p.url || 'https://example.com', window.location.origin);
                                return `
                                    <tr>
                                        <td><span class="rank-badge">#${idx + 1}</span></td>
                                        <td>
                                            <div class="table-page-title">${UI.escapeHtml(p.page_title || 'Untitled Page')}</div>
                                            <div class="table-page-sub">
                                                <a href="${UI.escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer">${UI.escapeHtml(urlObj.pathname)}</a>
                                                ${p.section_heading ? ` • <em>${UI.escapeHtml(p.section_heading)}</em>` : ''}
                                            </div>
                                            ${(sb.matched_terms || []).length > 0 ? `
                                                <div class="table-matched-terms">
                                                    Terms: ${(sb.matched_terms || []).map(t => `<span class="mini-term">${UI.escapeHtml(t)}</span>`).join('')}
                                                </div>
                                            ` : ''}
                                        </td>
                                        <td>${(sb.bm25_score || 0).toFixed(2)}</td>
                                        <td>+${(sb.title_boost || 0).toFixed(2)}</td>
                                        <td>+${(sb.heading_boost || 0).toFixed(2)}</td>
                                        <td>+${(sb.position_boost || 0).toFixed(2)}</td>
                                        <td>-${(sb.depth_penalty || 0).toFixed(2)}</td>
                                        <td><strong class="total-score-badge">${(sb.total_score || 0).toFixed(2)}</strong></td>
                                    </tr>
                                `;
                            }).join('')}
                        </tbody>
                    </table>
                </div>
            `;
        } else {
            passagesHtml = '<p class="text-muted">No individual passage scoring breakdown available.</p>';
        }

        return `
            <div class="transparency-section">
                <h4>1. Question Aspect Decomposition</h4>
                <div class="aspects-grid">
                    ${aspectsHtml}
                </div>
            </div>
            <div class="transparency-section">
                <h4>2. BM25 Passage Retrieval & Explainable Score Breakdown</h4>
                <p class="section-desc">
                    Every passage is scored using pure Python Okapi BM25 with Lucene IDF, boosted by title and section heading matches, and penalized by URL crawl depth.
                </p>
                ${passagesHtml}
            </div>
        `;
    },

    // ── Session History Sidebar ───────────────────────────────────────
    renderSessionHistory(sessions, onSelectSession) {
        const list = document.getElementById('session-history-list');
        if (!list) return;

        list.innerHTML = '';
        if (!sessions || sessions.length === 0) {
            list.innerHTML = '<div class="empty-history">No previous searches yet.</div>';
            return;
        }

        sessions.forEach(sess => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.dataset.sessionId = sess.id;

            const timeStr = sess.created_at 
                ? new Date(sess.created_at).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                : '';

            const statusClass = sess.status === 'done' ? 'badge-success' : (sess.status === 'cancelled' ? 'badge-warning' : 'badge-danger');

            item.innerHTML = `
                <div class="history-item-header">
                    <span class="history-domain">${UI.getDomain(sess.seed_url)}</span>
                    <span class="badge ${statusClass}">${sess.status}</span>
                </div>
                <div class="history-question">${UI.escapeHtml(sess.question)}</div>
                <div class="history-meta">
                    <span>${timeStr}</span>
                    <span>${sess.pages_crawled || 0} pages</span>
                </div>
            `;

            item.addEventListener('click', () => {
                document.querySelectorAll('.history-item').forEach(el => el.classList.remove('selected'));
                item.classList.add('selected');
                if (onSelectSession) onSelectSession(sess);
            });

            list.appendChild(item);
        });
    },

    // ── Utilities ─────────────────────────────────────────────────────
    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    getDomain(urlStr) {
        try {
            return new URL(urlStr).hostname;
        } catch (_) {
            return urlStr;
        }
    },

    formatMarkdown(text) {
        if (!text) return '';
        let escaped = UI.escapeHtml(text);

        // Convert ### Headings
        escaped = escaped.replace(/^### (.*$)/gim, '<h3>$1</h3>');
        escaped = escaped.replace(/^## (.*$)/gim, '<h2>$1</h2>');
        escaped = escaped.replace(/^# (.*$)/gim, '<h1>$1</h1>');

        // Bold **text**
        escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // Inline code `code`
        escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

        // Unordered list items - item
        escaped = escaped.replace(/^\- (.*$)/gim, '<li>$1</li>');
        // Wrap consecutive <li> in <ul>
        escaped = escaped.replace(/(<li>.*<\/li>(\n|.)*?)(?!<li>)/g, '<ul>$1</ul>');

        // Line breaks
        escaped = escaped.replace(/\n\n/g, '<p></p>');
        escaped = escaped.replace(/\n/g, '<br>');

        return escaped;
    }
};

window.UI = UI;
