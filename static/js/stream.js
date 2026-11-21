/**
 * SiteSage SSE Stream Manager (Vanilla JavaScript)
 * Connects to /api/search/{sessionId}/stream with auto-reconnection and event parsing.
 */

class SearchStreamManager {
    constructor() {
        this.eventSource = null;
        this.currentSessionId = null;
        this.lastEventId = 0;
        this.listeners = new Map();
        this.onAnyEvent = null;
        this.onError = null;
        this.onComplete = null;
        this.isClosed = true;
    }

    /**
     * Connect to SSE stream for a specific session.
     * @param {string} sessionId
     * @param {Object} callbacks
     */
    connect(sessionId, { onEvent, onError, onComplete } = {}) {
        this.disconnect();

        this.currentSessionId = sessionId;
        this.onAnyEvent = onEvent;
        this.onError = onError;
        this.onComplete = onComplete;
        this.isClosed = false;

        const streamUrl = `/api/search/${encodeURIComponent(sessionId)}/stream`;
        this.eventSource = new EventSource(streamUrl);

        // Standard event types broadcasted by pipeline
        const eventTypes = [
            'session_started',
            'crawling_started',
            'page_discovered',
            'page_crawled',
            'page_failed',
            'crawling_completed',
            'indexing_started',
            'indexing_completed',
            'retrieval_started',
            'evidence_found',
            'answer_generated',
            'polishing_started',
            'polishing_completed',
            'pipeline_completed',
            'session_cancelled',
            'pipeline_error'
        ];

        // Register listener for each event type
        eventTypes.forEach(type => {
            this.eventSource.addEventListener(type, (event) => {
                this._handleMessage(type, event);
            });
        });

        // Default message listener
        this.eventSource.onmessage = (event) => {
            this._handleMessage('message', event);
        };

        this.eventSource.onerror = (err) => {
            if (this.isClosed) return;
            console.warn('SSE connection interrupted, browser will attempt reconnection...', err);
            if (this.onError) {
                this.onError({
                    message: 'Reconnecting to live search progress...',
                    type: 'network_warning'
                });
            }
        };
    }

    _handleMessage(eventType, rawEvent) {
        if (this.isClosed) return;

        if (rawEvent.lastEventId) {
            this.lastEventId = parseInt(rawEvent.lastEventId, 10) || this.lastEventId;
        }

        let data = {};
        try {
            data = JSON.parse(rawEvent.data);
        } catch (e) {
            console.error('Failed to parse SSE JSON payload:', rawEvent.data);
            return;
        }

        if (data.event_id) {
            this.lastEventId = data.event_id;
        }

        // Notify global event handler
        if (this.onAnyEvent) {
            this.onAnyEvent(eventType, data);
        }

        // Specific event listeners
        if (this.listeners.has(eventType)) {
            this.listeners.get(eventType).forEach(cb => cb(data));
        }

        // Terminal event check
        if (eventType === 'pipeline_completed' || 
            eventType === 'session_cancelled' || 
            eventType === 'pipeline_error') {
            const isSuccess = eventType === 'pipeline_completed';
            const isCancelled = eventType === 'session_cancelled';
            
            setTimeout(() => {
                if (this.onComplete) {
                    this.onComplete({
                        eventType,
                        data,
                        isSuccess,
                        isCancelled
                    });
                }
                this.disconnect();
            }, 300);
        }
    }

    /**
     * Add listener for specific event type.
     */
    addEventListener(eventType, callback) {
        if (!this.listeners.has(eventType)) {
            this.listeners.set(eventType, new Set());
        }
        this.listeners.get(eventType).add(callback);
    }

    /**
     * Remove listener.
     */
    removeEventListener(eventType, callback) {
        if (this.listeners.has(eventType)) {
            this.listeners.get(eventType).delete(callback);
        }
    }

    /**
     * Terminate active stream.
     */
    disconnect() {
        this.isClosed = true;
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }
}

window.SearchStreamManager = SearchStreamManager;
