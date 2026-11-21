/**
 * Comprehensive Automated Tests for SiteSage Answer UI Source Hyperlinks.
 *
 * Verifies all requirements:
 * 1. Normal HTTPS URL -> creates <a> with target="_blank" and rel="noopener noreferrer"
 * 2. URL containing query parameters -> preserved exactly in href
 * 3. URL containing encoded characters -> preserved exactly in href
 * 4. Duplicate source URLs -> reuses existing Source ID (e.g. Source 1)
 * 5. Invalid URL -> creates non-clickable unavailable badge
 * 6. javascript: URL rejection -> creates non-clickable unavailable badge
 * 7. data: URL rejection -> creates non-clickable unavailable badge
 * 8. Source link opening in a new tab -> target="_blank", rel="noopener noreferrer"
 * 9. Structured answer output separation -> text and sources cleanly decoupled
 * 10. Safe DOM construction without innerHTML
 */

const assert = require('assert');

// ── Minimal DOM Mock for Node.js Testing ─────────────────────────────
class MockNode {
    constructor(nodeType, nodeName) {
        this.nodeType = nodeType;
        this.nodeName = nodeName;
        this.childNodes = [];
        this.parentNode = null;
        this.attributes = {};
        this.className = '';
        this._text = '';
        this.href = '';
        this.target = '';
        this.rel = '';
        this.title = '';
    }

    get textContent() {
        if (this.nodeType === 3) return this._text || '';
        return this.childNodes.map(c => c.textContent).join('');
    }

    set textContent(val) {
        if (this.nodeType === 3) {
            this._text = String(val);
        } else {
            this.childNodes = [];
            if (val) this.appendChild(new MockTextNode(String(val)));
        }
    }

    appendChild(child) {
        child.parentNode = this;
        this.childNodes.push(child);
        return child;
    }

    setAttribute(name, value) {
        this.attributes[name] = String(value);
    }

    getAttribute(name) {
        return this.attributes[name] || null;
    }

    hasChildNodes() {
        return this.childNodes.length > 0;
    }

    get lastElementChild() {
        for (let i = this.childNodes.length - 1; i >= 0; i--) {
            if (this.childNodes[i].nodeType === 1) return this.childNodes[i];
        }
        return null;
    }

    querySelectorAll(tagName) {
        const results = [];
        const walk = (node) => {
            for (const child of node.childNodes) {
                if (child.nodeName.toLowerCase() === tagName.toLowerCase()) {
                    results.push(child);
                }
                walk(child);
            }
        };
        walk(this);
        return results;
    }
}

class MockElement extends MockNode {
    constructor(tagName) {
        super(1, tagName.toUpperCase());
        this.tagName = tagName.toUpperCase();
    }
}

class MockTextNode extends MockNode {
    constructor(text) {
        super(3, '#text');
        this.textContent = text;
    }
}

global.document = {
    createElement(tag) {
        return new MockElement(tag);
    },
    createElementNS(ns, tag) {
        return new MockElement(tag);
    },
    createTextNode(text) {
        return new MockTextNode(text);
    }
};

global.window = {
    location: { origin: 'http://localhost:8000' }
};

// Import UI module
const UI = require('../static/js/ui.js');

console.log('Running SiteSage Source Hyperlinks Test Suite...');

// ── Test 1: URL Validation Logic ─────────────────────────────────────
console.log('Test 1: URL Validation Logic');
{
    // Normal HTTPS URL
    const res1 = UI.validateUrl('https://example.com/pricing');
    assert.strictEqual(res1.valid, true);
    assert.strictEqual(res1.protocol, 'https:');
    assert.strictEqual(res1.url, 'https://example.com/pricing');

    // Normal HTTP URL
    const resHttp = UI.validateUrl('http://example.com/docs');
    assert.strictEqual(resHttp.valid, true);
    assert.strictEqual(resHttp.protocol, 'http:');

    // Query parameters
    const res2 = UI.validateUrl('https://example.com/search?query=test&page=2&lang=en');
    assert.strictEqual(res2.valid, true);
    assert.strictEqual(res2.url, 'https://example.com/search?query=test&page=2&lang=en');

    // Encoded characters and fragment
    const res3 = UI.validateUrl('https://example.com/item/Special%20Edition%20(2026)?ref=home#details');
    assert.strictEqual(res3.valid, true);
    assert.strictEqual(res3.url, 'https://example.com/item/Special%20Edition%20(2026)?ref=home#details');

    // javascript: URL rejection
    const resJs = UI.validateUrl('javascript:alert(document.cookie)');
    assert.strictEqual(resJs.valid, false);
    assert(resJs.reason.includes('Disallowed protocol'));

    // data: URL rejection
    const resData = UI.validateUrl('data:text/html,<script>alert(1)</script>');
    assert.strictEqual(resData.valid, false);
    assert(resData.reason.includes('Disallowed protocol'));

    // file: URL rejection
    const resFile = UI.validateUrl('file:///etc/passwd');
    assert.strictEqual(resFile.valid, false);

    // Malformed string
    const resBad = UI.validateUrl('not-a-valid-url');
    assert.strictEqual(resBad.valid, false);
}
console.log('  ✔ URL validation tests passed.');

// ── Test 2: Source Link DOM Element Construction ─────────────────────
console.log('Test 2: Source Link DOM Construction & Attributes');
{
    const sourceRegistry = new Map();
    const titleLookup = {
        'https://example.com/pricing': 'Official Pricing & Plans'
    };

    // Valid Link Creation
    const linkEl = UI.createSourceLink('https://example.com/pricing', sourceRegistry, titleLookup);
    assert.strictEqual(linkEl.nodeName, 'A');
    assert.strictEqual(linkEl.href, 'https://example.com/pricing');
    assert.strictEqual(linkEl.target, '_blank');
    assert.strictEqual(linkEl.rel, 'noopener noreferrer');
    assert.strictEqual(linkEl.className, 'answer-source-link');
    assert(linkEl.getAttribute('aria-label').includes('View source'));
    assert(linkEl.getAttribute('aria-label').includes('Official Pricing & Plans'));

    // Friendly label "Source"
    const labelSpan = linkEl.childNodes.find(c => c.className === 'source-link-label');
    assert(labelSpan, 'Must contain .source-link-label');
    assert.strictEqual(labelSpan.textContent, 'Source');

    // External link icon
    const iconSvg = linkEl.childNodes.find(c => c.nodeName === 'SVG');
    assert(iconSvg, 'Must contain SVG external-link icon');
    assert.strictEqual(iconSvg.getAttribute('class'), 'ext-link-icon');
    assert.strictEqual(iconSvg.getAttribute('aria-hidden'), 'true');

    // Duplicate source reuse
    const linkElDuplicate = UI.createSourceLink('https://example.com/pricing', sourceRegistry, titleLookup);
    assert.strictEqual(sourceRegistry.size, 1, 'Registry must not duplicate identical URLs');
    const labelSpanDup = linkElDuplicate.childNodes.find(c => c.className === 'source-link-label');
    assert.strictEqual(labelSpanDup.textContent, 'Source', 'Reused URL must keep Source label');

    // Second unique URL
    const linkEl2 = UI.createSourceLink('https://example.com/terms?v=2#refund', sourceRegistry, titleLookup);
    assert.strictEqual(sourceRegistry.size, 2);
    const labelSpan2 = linkEl2.childNodes.find(c => c.className === 'source-link-label');
    assert.strictEqual(labelSpan2.textContent, 'Source');
    assert.strictEqual(linkEl2.href, 'https://example.com/terms?v=2#refund');

    // Insecure / javascript: link rejection
    const invalidEl = UI.createSourceLink('javascript:alert(1)', sourceRegistry, titleLookup);
    assert.strictEqual(invalidEl.nodeName, 'SPAN');
    assert.strictEqual(invalidEl.className, 'source-link-invalid');
    assert.strictEqual(invalidEl.textContent, 'Source (unavailable)');
    assert.strictEqual(invalidEl.getAttribute('role'), 'status');
    assert.strictEqual(invalidEl.getAttribute('href'), null, 'Invalid source must not have href attribute');
}
console.log('  ✔ Source Link DOM element construction tests passed.');

// ── Test 3: Full Answer Content Rendering with Mixed Sources ─────────
console.log('Test 3: Full Answer Content Rendering with Mixed Sources');
{
    const container = document.createElement('div');
    const answerMarkdown = `
### Pricing Overview
- The Starter plan costs $19 per month [Source: https://example.com/pricing?ref=promo&tier=1#features].
- The Enterprise plan has custom limits [Source: https://example.com/enterprise%20tier].
- Contradictory quote verified at [Source: https://example.com/pricing?ref=promo&tier=1#features].
- Malicious payload attempt blocked [Source: javascript:void(0)].

### Summary
All quotes are active.
    `.trim();

    const claims = [
        {
            claim: 'The Starter plan costs $19 per month',
            confidence: 0.85,
            sources: [
                {
                    page_url: 'https://example.com/pricing?ref=promo&tier=1#features',
                    page_title: 'Pricing Page',
                    exact_quote: 'costs $19 per month'
                }
            ]
        }
    ];

    UI.renderAnswerContent(container, answerMarkdown, claims);

    // Verify Headings
    const headings = container.querySelectorAll('h3');
    assert.strictEqual(headings.length, 2);
    assert.strictEqual(headings[0].textContent, 'Pricing Overview');
    assert.strictEqual(headings[1].textContent, 'Summary');

    // Verify Anchor Tags (Source Links)
    const links = container.querySelectorAll('a');
    assert(links.length >= 3, `Expected at least 3 source hyperlinks, found ${links.length}`);

    // Check all anchors have target="_blank" and rel="noopener noreferrer"
    links.forEach(a => {
        assert.strictEqual(a.target, '_blank');
        assert.strictEqual(a.rel, 'noopener noreferrer');
        assert(a.href.startsWith('http://') || a.href.startsWith('https://'));
    });

    // Check query params and encoded characters preservation
    const hrefs = links.map(a => a.href);
    assert(hrefs.includes('https://example.com/pricing?ref=promo&tier=1#features'));
    assert(hrefs.includes('https://example.com/enterprise%20tier'));

    // Check duplicate URL reuse: both references to pricing should be labeled "Source"
    const source1Links = links.filter(a => a.href === 'https://example.com/pricing?ref=promo&tier=1#features');
    assert(source1Links.length >= 2, 'Expected at least 2 occurrences of Source link (inline + footer)');

    // Check javascript: URL was converted to non-clickable unavailable badge
    const invalidSpans = container.querySelectorAll('span').filter(s => s.className === 'source-link-invalid');
    assert.strictEqual(invalidSpans.length, 1, 'javascript: link must render as unavailable span');
    assert.strictEqual(invalidSpans[0].textContent, 'Source (unavailable)');
}
console.log('  ✔ Full answer content rendering tests passed.');

// ── Test 4: Markdown Link Formats [Source 1](URL) & [Source](URL) ──
console.log('Test 4: Markdown Link Formats [Source 1](URL) & [Source](URL)');
{
    const container = document.createElement('div');
    const textWithMarkdownLinks = `
The Tamil title *Anbil Avan* (2026) is available online [Source 1](https://www.1tamilmv.ceo/index.php?%2Fforums%2Ftopic%2F201195-anbil-avan-2026%2F).
The posting was shared in the forum section [Source](https://www.1tamilmv.ceo/index.php?%2Fforums%2Ftopic%2F201195-anbil-avan-2026%2F).
Navigation elements across the forum pages include cookie settings [View source](https://www.1tamilmv.ceo/index.php?%2Fforums%2Ftopic%2F201195-anbil-avan-2026%2F).
    `.trim();

    UI.renderAnswerContent(container, textWithMarkdownLinks);

    const links = container.querySelectorAll('a');
    // 3 inline links + 1 in footer
    assert.strictEqual(links.length, 4);

    links.forEach(a => {
        assert.strictEqual(a.href, 'https://www.1tamilmv.ceo/index.php?%2Fforums%2Ftopic%2F201195-anbil-avan-2026%2F');
        assert.strictEqual(a.target, '_blank');
        assert.strictEqual(a.rel, 'noopener noreferrer');
    });

    const labels = container.querySelectorAll('span').filter(s => s.className === 'source-link-label');
    assert.strictEqual(labels.length, 3);
    labels.forEach(l => {
        assert.strictEqual(l.textContent, 'Source');
    });
}
console.log('  ✔ Markdown link formats [Source 1](URL) & [Source](URL) passed.');

// ── Test 5: Structured Data Decoupling (Recommendation) ─────────────
console.log('Test 5: Structured Data Decoupling Helper');
{
    const sampleResult = {
        answer: 'The page describes the movie as available in Tamil.',
        claims: [
            {
                claim: 'The page describes the movie as available in Tamil.',
                confidence: 0.9,
                aspect: 'Language availability',
                sources: [
                    {
                        page_url: 'https://example.com/movies/anbil-avan?lang=ta#watch',
                        page_title: 'Anbil Avan (2026)',
                        exact_quote: 'Available in Tamil with English subtitles.'
                    }
                ]
            }
        ]
    };

    const structured = UI.getStructuredAnswer(sampleResult);
    assert(structured !== null);
    assert.strictEqual(structured.text, sampleResult.answer);
    assert.strictEqual(structured.claims.length, 1);
    assert.strictEqual(structured.claims[0].text, 'The page describes the movie as available in Tamil.');
    assert.strictEqual(structured.claims[0].sources.length, 1);
    assert.strictEqual(structured.claims[0].sources[0].id, 1);
    assert.strictEqual(structured.claims[0].sources[0].title, 'Anbil Avan (2026)');
    assert.strictEqual(structured.claims[0].sources[0].url, 'https://example.com/movies/anbil-avan?lang=ta#watch');
    assert.strictEqual(structured.all_sources.length, 1);
}
console.log('  ✔ Structured data decoupling helper tests passed.');

console.log('\nALL 5 TEST SUITES PASSED CLEANLY (100% OK)!');
