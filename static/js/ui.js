/**
 * SiteSage UI Renderer & DOM Controller (Vanilla JavaScript)
 * Clean, human-crafted design with zero AI-slop tells.
 */

const UI = {
    eventLogCount: 0,

    // ── Toast Notifications ───────────────────────────────────────────
    showToast(message, type = 'info', duration = 3500) {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        let iconSvg = '';
        if (type === 'success') {
            iconSvg = `<svg class="toast-svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
        } else if (type === 'error') {
            iconSvg = `<svg class="toast-svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
        } else if (type === 'warning') {
            iconSvg = `<svg class="toast-svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`;
        } else {
            iconSvg = `<svg class="toast-svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
        }

        toast.innerHTML = `
            <span class="toast-icon-wrap">${iconSvg}</span>
            <span class="toast-message">${UI.escapeHtml(message)}</span>
        `;

        container.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add('visible'));

        setTimeout(() => {
            toast.classList.remove('visible');
            setTimeout(() => toast.remove(), 250);
        }, duration);
    },

    // ── Stage & Progress Helper ───────────────────────────────────────
    getStageLabel(stage, status) {
        if (status === 'cancelled') return { label: 'Cancelled', class: 'stage-cancelled' };
        if (status === 'error') return { label: 'Failed', class: 'stage-error' };

        const map = {
            'initialization': { label: 'Initializing', class: 'stage-init' },
            'crawling': { label: 'Crawling', class: 'stage-crawl' },
            'indexing': { label: 'Indexing Passages', class: 'stage-index' },
            'retrieval': { label: 'BM25 Ranking', class: 'stage-retrieval' },
            'extracting': { label: 'Extracting Evidence', class: 'stage-extract' },
            'polishing': { label: 'Polishing Readability', class: 'stage-polish' },
            'completed': { label: 'Complete', class: 'stage-done' },
        };
        return map[stage] || { label: stage || 'Active', class: 'stage-active' };
    },

    estimateProgressPercent(stage, status, pagesCrawled = 0, maxPages = 30) {
        if (status === 'done' || stage === 'completed') return 100;
        if (status === 'cancelled' || status === 'error') return 100;

        const crawlRatio = maxPages > 0 ? Math.min(pagesCrawled / maxPages, 1.0) : 0;

        switch (stage) {
            case 'initialization':
                return 5;
            case 'crawling':
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
        const countRemaining = document.getElementById('count-remaining');
        const countDiscovered = document.getElementById('count-discovered');
        const countQueued = document.getElementById('count-queued');
        const countFailed = document.getElementById('count-failed');
        const currentUrlText = document.getElementById('dash-current-url');

        const stageInfo = UI.getStageLabel(data.stage, data.status);
        if (stagePill) {
            stagePill.textContent = stageInfo.label;
            stagePill.className = `status-pill ${stageInfo.class}`;
        }

        const maxP = data.max_pages || 15;
        const crawledP = data.pages_crawled || 0;
        const remainingP = Math.max(0, maxP - crawledP);

        const percent = UI.estimateProgressPercent(
            data.stage,
            data.status,
            crawledP,
            maxP
        );

        if (progressBar) progressBar.style.width = `${percent}%`;
        if (progressPercent) progressPercent.textContent = `${percent}%`;

        if (countCrawled) countCrawled.textContent = `${crawledP} / ${maxP}`;
        if (countRemaining) countRemaining.textContent = remainingP;
        if (countDiscovered) countDiscovered.textContent = data.pages_discovered || 0;
        if (countQueued) countQueued.textContent = data.pages_queued || 0;
        if (countFailed) countFailed.textContent = data.pages_failed || 0;

        if (currentUrlText) {
            currentUrlText.textContent = data.current_url || 'Analyzing links and page content...';
        }
    },

    appendEventLog(eventType, data) {
        const feed = document.getElementById('dash-activity-feed');
        if (!feed) return;

        UI.eventLogCount = (UI.eventLogCount || 0) + 1;
        const toggleLabel = document.getElementById('feed-toggle-label');
        if (toggleLabel) {
            toggleLabel.textContent = `Live activity log (${UI.eventLogCount} events)`;
        }

        const item = document.createElement('div');
        item.className = 'feed-item';

        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const stageBadge = UI.getStageLabel(data.stage, data.status).label;

        let dotClass = 'feed-dot-default';
        if (eventType === 'page_crawled') dotClass = 'feed-dot-crawl';
        if (eventType === 'page_discovered') dotClass = 'feed-dot-disc';
        if (eventType === 'indexing_completed') dotClass = 'feed-dot-index';
        if (eventType === 'evidence_found') dotClass = 'feed-dot-evidence';
        if (eventType === 'pipeline_completed') dotClass = 'feed-dot-done';
        if (eventType === 'session_cancelled') dotClass = 'feed-dot-warn';
        if (eventType === 'pipeline_error' || eventType === 'page_failed') dotClass = 'feed-dot-err';

        item.innerHTML = `
            <span class="feed-time">${time}</span>
            <span class="feed-dot ${dotClass}" aria-hidden="true"></span>
            <span class="feed-msg">
                <span class="feed-stage-tag">${UI.escapeHtml(stageBadge)}</span>
                <span class="feed-text">${UI.escapeHtml(data.message || eventType)}</span>
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

        // 1. Determine Polish Status Badge and Explanation
        let polishBadge = '';
        let outcomeBanner = '';

        if (result.polish_status === 'improved' || result.ai_polished) {
            polishBadge = `
                <span class="badge badge-ai" title="Readability improved while strictly preserving factual evidence">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"></path></svg>
                    AI Improved
                </span>
            `;
            outcomeBanner = `
                <div class="polish-outcome-banner outcome-improved">
                    <span class="outcome-pill">AI Improved</span>
                    <span class="outcome-desc">${UI.escapeHtml(result.polish_reason || 'Prose transitions and readability enhanced while preserving all verified numbers and citations.')}</span>
                </div>
            `;
        } else if (result.polish_status === 'original_retained') {
            polishBadge = `
                <span class="badge badge-warning" title="Factual guard retained original evidence">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                    Original Retained
                </span>
            `;
            outcomeBanner = `
                <div class="polish-outcome-banner outcome-retained">
                    <span class="outcome-pill">Original Retained</span>
                    <span class="outcome-desc">${UI.escapeHtml(result.polish_reason || 'Safety validator retained verified deterministic evidence.')}</span>
                </div>
            `;
        } else if (result.polish_status === 'unavailable') {
            polishBadge = `
                <span class="badge badge-meta" title="AI polishing unavailable; deterministic evidence presented">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>
                    AI Unavailable
                </span>
            `;
            outcomeBanner = `
                <div class="polish-outcome-banner outcome-unavailable">
                    <span class="outcome-pill">AI Unavailable</span>
                    <span class="outcome-desc">${UI.escapeHtml(result.polish_reason || 'AI polishing service not configured in .env; displaying verified deterministic evidence.')}</span>
                </div>
            `;
        } else {
            polishBadge = `
                <span class="badge badge-det" title="Extracted directly from website evidence with zero external additions">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                    Verified Evidence
                </span>
            `;
        }

        const pagesCrawledText = `${result.pages_crawled || 0} page${result.pages_crawled === 1 ? '' : 's'} crawled`;

        // Primary Answer Header & Card
        const answerCard = document.createElement('div');
        answerCard.className = 'answer-card card';
        answerCard.innerHTML = `
            <div class="answer-header">
                <div class="answer-title-group">
                    <h2 class="section-title">Evidence-Supported Answer</h2>
                    <div class="badge-group">
                        ${polishBadge}
                        <span class="badge badge-meta">${pagesCrawledText}</span>
                    </div>
                </div>
                <button class="btn btn-secondary btn-sm" id="btn-copy-answer" title="Copy response to clipboard">
                    <svg class="btn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                    <span>Copy Answer</span>
                </button>
            </div>
            ${outcomeBanner}
            <div class="answer-body markdown-content" id="answer-text-content"></div>
        `;
        container.appendChild(answerCard);

        // Populate answer content safely via DOM construction with clickable source hyperlinks
        const answerBodyEl = answerCard.querySelector('#answer-text-content');
        if (answerBodyEl) {
            UI.renderAnswerContent(
                answerBodyEl,
                result.answer || 'No direct answer could be extracted from the crawled pages.',
                result.claims || []
            );
        }

        // Bind copy button
        const copyBtn = answerCard.querySelector('#btn-copy-answer');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(result.answer || '')
                    .then(() => {
                        UI.showToast('Answer copied to clipboard', 'success');
                        copyBtn.innerHTML = `
                            <svg class="btn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                                <polyline points="20 6 9 17 4 12"></polyline>
                            </svg>
                            <span>Copied</span>
                        `;
                        setTimeout(() => {
                            copyBtn.innerHTML = `
                                <svg class="btn-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                </svg>
                                <span>Copy Answer</span>
                            `;
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
                    <svg class="alert-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="12" y1="8" x2="12" y2="12"></line>
                        <line x1="12" y1="16" x2="12.01" y2="16"></line>
                    </svg>
                    <strong>Unanswered Inquiry Aspects</strong>
                </div>
                <p>The target pages did not contain sufficient evidence to address these specific parts:</p>
                <ul class="alert-list">
                    ${result.missing_aspects.map(a => `<li>${UI.escapeHtml(a)}</li>`).join('')}
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
                    <svg class="alert-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                        <line x1="12" y1="9" x2="12" y2="13"></line>
                        <line x1="12" y1="17" x2="12.01" y2="17"></line>
                    </svg>
                    <strong>Contradictory Evidence Detected Across Pages</strong>
                </div>
                <p>Distinct pages on this website state conflicting information:</p>
                ${result.conflicts.map(c => `
                    <div class="conflict-item">
                        <div class="conflict-aspect">Aspect: <em>${UI.escapeHtml(c.aspect)}</em></div>
                        <ul class="conflict-quotes">
                            ${(c.conflicting_statements || []).map(s => `<li>&ldquo;${UI.escapeHtml(s)}&rdquo;</li>`).join('')}
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
                <div class="card-section-header">
                    <h3 class="section-subtitle">
                        Verified Claims &amp; Verbatim Sources (${result.claims.length})
                    </h3>
                </div>
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
                    <svg class="accordion-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                        <path d="M11 8v6M8 11h6"></path>
                    </svg>
                    <h3>Advanced Search Transparency (BM25 Ranking Breakdown)</h3>
                </div>
                <svg class="accordion-chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="6 9 12 15 18 9"></polyline>
                </svg>
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
            });
        }
    },

    renderClaimItem(c, index) {
        const confPercent = Math.round((c.confidence || 0) * 100);
        let confClass = 'conf-high';
        if (confPercent < 60) confClass = 'conf-med';
        if (confPercent < 40) confClass = 'conf-low';

        const sourcesHtml = (c.sources || []).map(s => {
            let hostname = '';
            let pathname = '';
            try {
                const urlObj = new URL(s.page_url, window.location.origin);
                hostname = urlObj.hostname;
                pathname = urlObj.pathname.length > 40
                    ? urlObj.pathname.substring(0, 37) + '...'
                    : urlObj.pathname || '/';
            } catch (_) {
                hostname = s.page_url;
                pathname = '';
            }

            return `
                <div class="source-ref-item">
                    <div class="source-header-row">
                        ${s.page_title ? `<div class="source-page-title">${UI.escapeHtml(s.page_title)}</div>` : ''}
                        <a href="${UI.escapeHtml(s.page_url)}" target="_blank" rel="noopener noreferrer" class="source-url-link" title="${UI.escapeHtml(s.page_url)}">
                            <span class="source-domain">${UI.escapeHtml(hostname)}</span>
                            <span class="source-path">${UI.escapeHtml(pathname)}</span>
                            <svg class="ext-link-icon" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                                <polyline points="15 3 21 3 21 9"></polyline>
                                <line x1="10" y1="14" x2="21" y2="3"></line>
                            </svg>
                        </a>
                    </div>
                    ${s.exact_quote ? `
                        <details class="quote-accordion">
                            <summary class="quote-summary">
                                <span>Verbatim passage quote ${s.section_heading ? '&sect; ' + UI.escapeHtml(s.section_heading) : ''} #${s.passage_id || ''}</span>
                                <svg class="quote-chevron" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                            </summary>
                            <blockquote class="exact-quote">
                                &ldquo;${UI.escapeHtml(s.exact_quote)}&rdquo;
                            </blockquote>
                        </details>
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
                    <div class="confidence-pill ${confClass}" title="Calibrated evidence score based on keyword coverage and multi-source corroboration">
                        ${confPercent}% match
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
                <div class="aspect-title">
                    <span class="aspect-dot"></span>
                    <span>${UI.escapeHtml(a.aspect)}</span>
                </div>
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
                                <th>Source URL &amp; Heading</th>
                                <th title="Okapi BM25 base term relevance score">BM25 Match</th>
                                <th title="Additive boost for keyword matching page title">Title Bonus</th>
                                <th title="Additive boost for keyword matching section heading">Heading Bonus</th>
                                <th title="Additive boost for passage appearing early in page">Position Bonus</th>
                                <th title="Score penalty applied to deep crawl URLs">Depth Penalty</th>
                                <th title="Final ranking score">Relevance Score</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${passages.slice(0, 10).map((sp, idx) => {
                                const p = sp.passage || {};
                                const sb = sp.score_breakdown || {};
                                let pathname = p.url || '';
                                try {
                                    const u = new URL(p.url || 'https://example.com', window.location.origin);
                                    pathname = u.pathname || '/';
                                } catch (_) {}

                                return `
                                    <tr>
                                        <td><span class="rank-badge">#${idx + 1}</span></td>
                                        <td>
                                            <div class="table-page-title">${UI.escapeHtml(p.page_title || 'Web Page')}</div>
                                            <div class="table-page-sub">
                                                <a href="${UI.escapeHtml(p.url)}" target="_blank" rel="noopener noreferrer">${UI.escapeHtml(pathname)}</a>
                                                ${p.section_heading ? ` &bull; <em>${UI.escapeHtml(p.section_heading)}</em>` : ''}
                                            </div>
                                            ${(sb.matched_terms || []).length > 0 ? `
                                                <div class="table-matched-terms">
                                                    Matched terms: ${(sb.matched_terms || []).map(t => `<span class="mini-term">${UI.escapeHtml(t)}</span>`).join('')}
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
                <h4>Aspect Decomposition</h4>
                <div class="aspects-grid">
                    ${aspectsHtml}
                </div>
            </div>
            <div class="transparency-section">
                <h4>BM25 Passage Retrieval &amp; Explainable Scores</h4>
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
    },

    // ── Safe DOM Source Hyperlinks & Structured Answers ─────────────────
    validateUrl(rawUrl) {
        if (!rawUrl || typeof rawUrl !== 'string') {
            return { valid: false, url: '', reason: 'Empty URL' };
        }
        const trimmed = rawUrl.trim();
        try {
            const parsed = new URL(trimmed);
            if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
                return {
                    valid: true,
                    url: trimmed,
                    parsed: parsed,
                    protocol: parsed.protocol,
                    hostname: parsed.hostname
                };
            }
            return {
                valid: false,
                url: trimmed,
                reason: `Disallowed protocol: ${parsed.protocol}`
            };
        } catch (_) {
            return {
                valid: false,
                url: trimmed,
                reason: 'Malformed URL'
            };
        }
    },

    createExtLinkIcon() {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'ext-link-icon');
        svg.setAttribute('width', '11');
        svg.setAttribute('height', '11');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.setAttribute('aria-hidden', 'true');

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6');
        svg.appendChild(path);

        const polyline = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        polyline.setAttribute('points', '15 3 21 3 21 9');
        svg.appendChild(polyline);

        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', '10');
        line.setAttribute('y1', '14');
        line.setAttribute('x2', '21');
        line.setAttribute('y2', '3');
        svg.appendChild(line);

        return svg;
    },

    createSourceLink(rawUrl, sourceRegistry, titleLookup = {}) {
        const validation = UI.validateUrl(rawUrl);

        if (!validation.valid) {
            const span = document.createElement('span');
            span.className = 'source-link-invalid';
            span.setAttribute('role', 'status');
            span.title = `Unavailable or insecure source: ${rawUrl}`;
            span.textContent = 'Source (unavailable)';
            return span;
        }

        const exactUrl = validation.url;
        let entry = sourceRegistry.get(exactUrl);

        if (!entry) {
            const id = sourceRegistry.size + 1;
            const domain = validation.hostname || UI.getDomain(exactUrl);
            const title = (titleLookup && titleLookup[exactUrl]) ? titleLookup[exactUrl] : domain;
            entry = {
                id: id,
                url: exactUrl,
                domain: domain,
                title: title
            };
            sourceRegistry.set(exactUrl, entry);
        }

        const a = document.createElement('a');
        a.href = exactUrl;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        a.className = 'answer-source-link';
        a.title = entry.title ? `${entry.title} — ${exactUrl} (opens in new tab)` : `${exactUrl} (opens in new tab)`;
        a.setAttribute('aria-label', `View source: ${entry.title || entry.domain} (${exactUrl})`);

        const label = document.createElement('span');
        label.className = 'source-link-label';
        label.textContent = 'Source';
        a.appendChild(label);

        a.appendChild(UI.createExtLinkIcon());
        return a;
    },

    appendCitationGroup(parentEl, rawUrlsString, sourceRegistry, titleLookup = {}) {
        if (!rawUrlsString || !rawUrlsString.trim()) return;

        // Split multiple URLs separated by comma followed by whitespace, or whitespace
        const urlTokens = rawUrlsString.split(/,\s+|\s+/).map(u => u.trim()).filter(Boolean);

        const group = document.createElement('span');
        group.className = 'answer-citation-group';

        urlTokens.forEach(token => {
            // Strip accidental enclosing punctuation without damaging query params or fragments
            const cleanToken = token.replace(/^[<(\[]+|[>)\],;.]+$/g, '');
            if (cleanToken) {
                const linkEl = UI.createSourceLink(cleanToken, sourceRegistry, titleLookup);
                group.appendChild(linkEl);
            }
        });

        if (group.hasChildNodes()) {
            parentEl.appendChild(group);
        }
    },

    appendFormattedText(parentEl, text) {
        if (!text) return;

        // Safely parse inline markdown: **bold** and `code` without innerHTML
        const parts = text.split(/(\*\*.*?\*\*|`[^`]+`)/g);

        parts.forEach(part => {
            if (!part) return;
            if (part.startsWith('**') && part.endsWith('**') && part.length >= 4) {
                const strong = document.createElement('strong');
                strong.textContent = part.slice(2, -2);
                parentEl.appendChild(strong);
            } else if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
                const code = document.createElement('code');
                code.textContent = part.slice(1, -1);
                parentEl.appendChild(code);
            } else {
                parentEl.appendChild(document.createTextNode(part));
            }
        });
    },

    parseInlineIntoElement(text, parentEl, sourceRegistry, titleLookup = {}) {
        if (!text) return;

        // Matches:
        // 1. [Source 1](https://...) or [Source](https://...) or [View source](https://...)
        // 2. [Source: https://...] or [Source 1: https://...]
        const citationRegex = /\[(?:Source|View source|Link)(?:\s*\d*)?\]\((https?:\/\/[^\s)]+)\)|\[(?:Source|View source)(?:\s*\d*)?:\s*([^\]]+)\]/gi;
        let lastIndex = 0;
        let match;

        while ((match = citationRegex.exec(text)) !== null) {
            const before = text.substring(lastIndex, match.index);
            if (before) {
                UI.appendFormattedText(parentEl, before);
            }
            const rawUrls = match[1] || match[2];
            UI.appendCitationGroup(parentEl, rawUrls, sourceRegistry, titleLookup);
            lastIndex = citationRegex.lastIndex;
        }

        const remaining = text.substring(lastIndex);
        if (remaining) {
            UI.appendFormattedText(parentEl, remaining);
        }
    },

    renderAnswerContent(container, answerText, claims = []) {
        if (!container) return;
        container.textContent = ''; // Safe DOM wipe

        if (!answerText || !answerText.trim()) {
            const p = document.createElement('p');
            p.className = 'text-muted';
            p.textContent = 'No direct answer could be extracted from the crawled pages.';
            container.appendChild(p);
            return;
        }

        // Prepopulate title lookup & registry from structured claims data
        const titleLookup = {};
        const sourceRegistry = new Map();

        (claims || []).forEach(c => {
            (c.sources || []).forEach(s => {
                if (s && s.page_url) {
                    const validation = UI.validateUrl(s.page_url);
                    if (validation.valid) {
                        const url = validation.url;
                        if (s.page_title) {
                            titleLookup[url] = s.page_title;
                        }
                        if (!sourceRegistry.has(url)) {
                            sourceRegistry.set(url, {
                                id: sourceRegistry.size + 1,
                                url: url,
                                domain: validation.hostname || UI.getDomain(url),
                                title: s.page_title || validation.hostname
                            });
                        }
                    }
                }
            });
        });

        const lines = answerText.split('\n');
        let currentUl = null;

        lines.forEach(rawLine => {
            const trimmed = rawLine.trim();

            if (!trimmed) {
                currentUl = null;
                return;
            }

            // Headings (###, ##, #)
            const headingMatch = trimmed.match(/^(#{1,3})\s+(.*)$/);
            if (headingMatch) {
                currentUl = null;
                const level = headingMatch[1].length;
                const headingEl = document.createElement(`h${level}`);
                UI.parseInlineIntoElement(headingMatch[2], headingEl, sourceRegistry, titleLookup);
                container.appendChild(headingEl);
                return;
            }

            // Bullet list items (- or *)
            const listMatch = trimmed.match(/^[-*]\s+(.*)$/);
            if (listMatch) {
                if (!currentUl) {
                    currentUl = document.createElement('ul');
                    container.appendChild(currentUl);
                }
                const li = document.createElement('li');
                UI.parseInlineIntoElement(listMatch[1], li, sourceRegistry, titleLookup);
                currentUl.appendChild(li);
                return;
            }

            // Standalone Source line (from deterministic output: "Source: url1, url2")
            const sourceLineMatch = trimmed.match(/^Source:\s*(.+)$/i);
            if (sourceLineMatch) {
                const sourceRow = document.createElement('div');
                sourceRow.className = 'answer-source-row';

                const label = document.createElement('span');
                label.className = 'answer-source-row-label';
                label.textContent = 'Sources:';
                sourceRow.appendChild(label);

                UI.appendCitationGroup(sourceRow, sourceLineMatch[1], sourceRegistry, titleLookup);

                if (currentUl && currentUl.lastElementChild) {
                    currentUl.lastElementChild.appendChild(sourceRow);
                } else {
                    container.appendChild(sourceRow);
                }
                return;
            }

            // Regular paragraph
            currentUl = null;
            const p = document.createElement('p');
            UI.parseInlineIntoElement(rawLine, p, sourceRegistry, titleLookup);
            container.appendChild(p);
        });

        // Structured Sources Footer (if any sources were cited)
        if (sourceRegistry.size > 0) {
            const footer = document.createElement('div');
            footer.className = 'answer-sources-footer';

            const footerHeader = document.createElement('div');
            footerHeader.className = 'answer-sources-header';
            const footerTitle = document.createElement('span');
            footerTitle.className = 'sources-footer-title';
            footerTitle.textContent = `Sources Cited in Answer (${sourceRegistry.size})`;
            footerHeader.appendChild(footerTitle);
            footer.appendChild(footerHeader);

            const pillsContainer = document.createElement('div');
            pillsContainer.className = 'answer-sources-pills';

            sourceRegistry.forEach(entry => {
                const card = document.createElement('a');
                card.href = entry.url;
                card.target = '_blank';
                card.rel = 'noopener noreferrer';
                card.className = 'source-footer-card';
                card.setAttribute('aria-label', `View source: ${entry.title || entry.domain} (${entry.url})`);
                card.title = entry.title ? `${entry.title} — ${entry.url} (opens in new tab)` : `${entry.url} (opens in new tab)`;

                const name = document.createElement('span');
                name.className = 'source-footer-name';
                name.textContent = entry.title || entry.domain;
                card.appendChild(name);

                const domain = document.createElement('span');
                domain.className = 'source-footer-domain';
                domain.textContent = entry.domain;
                card.appendChild(domain);

                card.appendChild(UI.createExtLinkIcon());
                pillsContainer.appendChild(card);
            });

            footer.appendChild(pillsContainer);
            container.appendChild(footer);
        }
    },

    getStructuredAnswer(result) {
        if (!result) return null;
        const sourceMap = new Map();
        let sourceCounter = 1;

        const getSourceId = (url, title) => {
            if (!sourceMap.has(url)) {
                sourceMap.set(url, {
                    id: sourceCounter++,
                    url: url,
                    title: title || UI.getDomain(url)
                });
            }
            return sourceMap.get(url);
        };

        const structuredClaims = (result.claims || []).map(c => {
            const sources = (c.sources || []).map(s => {
                const entry = getSourceId(s.page_url, s.page_title);
                return {
                    id: entry.id,
                    title: s.page_title || entry.title,
                    url: s.page_url,
                    exact_quote: s.exact_quote,
                    section_heading: s.section_heading
                };
            });
            return {
                text: c.claim,
                confidence: c.confidence,
                aspect: c.aspect,
                sources: sources
            };
        });

        return {
            text: result.answer,
            claims: structuredClaims,
            all_sources: Array.from(sourceMap.values())
        };
    }
};

if (typeof window !== 'undefined') {
    window.UI = UI;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = UI;
}