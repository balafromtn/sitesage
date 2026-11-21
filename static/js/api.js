/**
 * SiteSage API Client (Vanilla JavaScript)
 * Communicates with the FastAPI backend.
 */

const API = {
    /**
     * Launch a new search session.
     * @param {string} url - Seed website URL
     * @param {string} question - Natural language question
     * @param {number} maxPages - Page cap (1-30)
     * @param {boolean} polish - Optional AI answer polisher flag
     * @returns {Promise<{session_id: string}>}
     */
    async startSearch(url, question, maxPages = 15, polish = false) {
        const response = await fetch('/api/search', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url.trim(),
                question: question.trim(),
                max_pages: Number(maxPages),
                polish: Boolean(polish),
            }),
        });

        if (!response.ok) {
            let errorMsg = 'Failed to initiate search.';
            try {
                const errData = await response.json();
                if (errData.detail) {
                    errorMsg = typeof errData.detail === 'string' 
                        ? errData.detail 
                        : JSON.stringify(errData.detail);
                }
            } catch (_) {}
            throw new Error(errorMsg);
        }

        return await response.json();
    },

    /**
     * Retrieve status summary for a session.
     * @param {string} sessionId
     * @returns {Promise<Object>}
     */
    async getStatus(sessionId) {
        const response = await fetch(`/api/search/${encodeURIComponent(sessionId)}/status`);
        if (!response.ok) {
            throw new Error(`Failed to fetch status (${response.status})`);
        }
        return await response.json();
    },

    /**
     * Retrieve final search results for a session.
     * @param {string} sessionId
     * @param {boolean} polish
     * @returns {Promise<Object>} SearchResult
     */
    async getResults(sessionId, polish = false) {
        const url = `/api/search/${encodeURIComponent(sessionId)}/results?polish=${Boolean(polish)}`;
        const response = await fetch(url);
        if (!response.ok) {
            let errorMsg = 'Failed to load search results.';
            try {
                const errData = await response.json();
                if (errData.detail) errorMsg = errData.detail;
            } catch (_) {}
            throw new Error(errorMsg);
        }
        return await response.json();
    },

    /**
     * Cancel an active search pipeline.
     * @param {string} sessionId
     * @returns {Promise<{session_id: string, cancelled: boolean}>}
     */
    async cancelSearch(sessionId) {
        const response = await fetch(`/api/search/${encodeURIComponent(sessionId)}/cancel`, {
            method: 'POST',
        });
        if (!response.ok) {
            throw new Error(`Failed to cancel search (${response.status})`);
        }
        return await response.json();
    },

    /**
     * Fetch recent search sessions.
     * @param {number} limit
     * @returns {Promise<Array>}
     */
    async getSessions(limit = 20) {
        const response = await fetch(`/api/sessions?limit=${Number(limit)}`);
        if (!response.ok) {
            throw new Error(`Failed to load sessions (${response.status})`);
        }
        return await response.json();
    },
};

window.API = API;
