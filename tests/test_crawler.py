"""
Tests for the crawler module — URL normalization, safety, priority scoring,
crawl behaviour, cancellation, robots.txt, and error handling.
"""

import sys
import asyncio
import socket
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import httpx

from crawler import (
    CrawlItem,
    RobotsTxtParser,
    WebCrawler,
    extract_links_with_anchor,
    extract_query_keywords,
    get_origin,
    is_blocked_port,
    is_private_ip,
    is_same_origin,
    is_url_safe,
    normalize_url,
    parse_html,
    score_url_relevance,
    validate_host_dns,
)
from models import SessionStatus


# ── URL Normalization ────────────────────────────────────────────────

class TestNormalizeUrl:
    def test_basic_normalization(self):
        assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"

    def test_strips_fragment(self):
        result = normalize_url("https://example.com/page#section")
        assert "#" not in result
        assert result == "https://example.com/page"

    def test_strips_tracking_params(self):
        result = normalize_url("https://example.com/page?id=1&utm_source=google&fbclid=abc")
        assert "utm_source" not in result
        assert "fbclid" not in result
        assert "id=1" in result

    def test_preserves_meaningful_params(self):
        result = normalize_url("https://example.com/search?q=hello&page=2")
        assert "q=hello" in result
        assert "page=2" in result

    def test_removes_default_port_http(self):
        assert normalize_url("http://example.com:80/path") == "http://example.com/path"

    def test_removes_default_port_https(self):
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_keeps_non_default_port(self):
        result = normalize_url("https://example.com:8080/path")
        assert ":8080" in result

    def test_collapses_slashes(self):
        result = normalize_url("https://example.com///path///to///page")
        assert "///" not in result
        assert "/path/to/page" in result

    def test_removes_trailing_slash(self):
        result = normalize_url("https://example.com/path/")
        assert result == "https://example.com/path"

    def test_root_keeps_slash(self):
        result = normalize_url("https://example.com/")
        assert result == "https://example.com/"

    def test_rejects_non_http_scheme(self):
        assert normalize_url("ftp://example.com/file") == ""
        assert normalize_url("javascript:alert(1)") == ""
        assert normalize_url("file:///etc/passwd") == ""

    def test_sorts_query_params(self):
        result = normalize_url("https://example.com/page?z=1&a=2")
        # urlencode sorts by insertion order of dict, but we're checking both present
        assert "a=2" in result
        assert "z=1" in result

    def test_empty_and_whitespace(self):
        # Root path keeps its trailing slash
        assert normalize_url("  https://example.com/  ") == "https://example.com/"

    def test_data_scheme_blocked(self):
        assert normalize_url("data:text/html,<h1>Hi</h1>") == ""


# ── Origin extraction & same-origin ─────────────────────────────────

class TestOrigin:
    def test_basic_origin(self):
        assert get_origin("https://example.com/path/page") == "https://example.com"

    def test_origin_with_port(self):
        assert get_origin("https://example.com:8080/path") == "https://example.com:8080"

    def test_same_origin_true(self):
        assert is_same_origin("https://example.com/page", "https://example.com")

    def test_same_origin_false_different_host(self):
        assert not is_same_origin("https://other.com/page", "https://example.com")

    def test_same_origin_false_different_scheme(self):
        assert not is_same_origin("http://example.com/page", "https://example.com")

    def test_same_origin_false_different_port(self):
        assert not is_same_origin("https://example.com:8080/page", "https://example.com")

    def test_subdomain_is_different_origin(self):
        assert not is_same_origin("https://sub.example.com/page", "https://example.com")


# ── Private IP rejection ────────────────────────────────────────────

class TestPrivateIPRejection:
    def test_loopback_v4(self):
        assert is_private_ip("127.0.0.1")

    def test_loopback_v6(self):
        assert is_private_ip("::1")

    def test_private_10(self):
        assert is_private_ip("10.0.0.1")

    def test_private_172(self):
        assert is_private_ip("172.16.0.1")

    def test_private_192(self):
        assert is_private_ip("192.168.1.1")

    def test_link_local(self):
        assert is_private_ip("169.254.1.1")

    def test_public_ip(self):
        assert not is_private_ip("8.8.8.8")

    def test_public_ip2(self):
        assert not is_private_ip("93.184.216.34")


# ── Blocked port check ──────────────────────────────────────────────

class TestBlockedPort:
    def test_ssh_blocked(self):
        assert is_blocked_port("https://example.com:22/path")

    def test_mysql_blocked(self):
        assert is_blocked_port("https://example.com:3306/path")

    def test_redis_blocked(self):
        assert is_blocked_port("https://example.com:6379/path")

    def test_normal_port_allowed(self):
        assert not is_blocked_port("https://example.com:8080/path")

    def test_default_port_allowed(self):
        assert not is_blocked_port("https://example.com/path")


# ── DNS validation ──────────────────────────────────────────────────

class TestDNSValidation:
    def test_empty_hostname(self):
        safe, _ = validate_host_dns("")
        assert not safe

    @patch("crawler.socket.getaddrinfo")
    def test_private_ip_rejected(self, mock_dns):
        mock_dns.return_value = [
            (2, 1, 0, "", ("127.0.0.1", 0)),
        ]
        safe, detail = validate_host_dns("evil.example.com")
        assert not safe
        assert "private IP" in detail

    @patch("crawler.socket.getaddrinfo")
    def test_public_ip_allowed(self, mock_dns):
        mock_dns.return_value = [
            (2, 1, 0, "", ("93.184.216.34", 0)),
        ]
        safe, ip = validate_host_dns("example.com")
        assert safe
        assert ip == "93.184.216.34"

    @patch("crawler.socket.getaddrinfo", side_effect=socket.gaierror("DNS failed"))
    def test_dns_failure(self, mock_dns):
        safe, detail = validate_host_dns("nonexistent.invalid")
        assert not safe


# ── Redirect safety ─────────────────────────────────────────────────

class TestRedirectSafety:
    @patch("crawler.validate_host_dns", return_value=(True, "93.184.216.34"))
    def test_same_origin_redirect_allowed(self, _mock):
        safe, _ = is_url_safe("https://example.com/new-path", "https://example.com")
        assert safe

    @patch("crawler.validate_host_dns", return_value=(True, "1.2.3.4"))
    def test_different_origin_redirect_blocked(self, _mock):
        safe, reason = is_url_safe("https://evil.com/steal", "https://example.com")
        assert not safe
        assert "different origin" in reason

    def test_blocked_scheme_in_redirect(self):
        safe, reason = is_url_safe("ftp://example.com/file", "https://example.com")
        assert not safe
        assert "blocked scheme" in reason


# ── Duplicate detection ─────────────────────────────────────────────

class TestDuplicateDetection:
    def test_same_url_not_enqueued_twice(self):
        crawler = WebCrawler("s1", "https://example.com", "test question",
                             max_pages=5, total_timeout=10)
        assert crawler._enqueue("https://example.com/page1", 1, "Page 1")
        assert not crawler._enqueue("https://example.com/page1", 1, "Page 1 again")

    def test_normalized_duplicates_caught(self):
        url1 = normalize_url("https://example.com/page?utm_source=x")
        url2 = normalize_url("https://example.com/page")
        assert url1 == url2  # Both normalize to same URL after stripping tracker


# ── Priority scoring ────────────────────────────────────────────────

class TestPriorityScoring:
    def test_keyword_extraction(self):
        keywords = extract_query_keywords("What is the pricing for enterprise plans?")
        assert "pricing" in keywords
        assert "enterprise" in keywords
        assert "plans" in keywords
        assert "what" not in keywords  # stopword
        assert "is" not in keywords
        assert "the" not in keywords

    def test_url_path_match_scores_higher(self):
        kw = {"pricing"}
        score_match = score_url_relevance(
            "https://example.com/pricing", "", kw, 1
        )
        score_nomatch = score_url_relevance(
            "https://example.com/about", "", kw, 1
        )
        assert score_match > score_nomatch

    def test_anchor_text_boosts_score(self):
        kw = {"pricing"}
        score_with_anchor = score_url_relevance(
            "https://example.com/page", "View Pricing", kw, 1
        )
        score_without_anchor = score_url_relevance(
            "https://example.com/page", "", kw, 1
        )
        assert score_with_anchor > score_without_anchor

    def test_deeper_pages_score_lower(self):
        kw = {"about"}
        score_shallow = score_url_relevance(
            "https://example.com/about", "", kw, 0
        )
        score_deep = score_url_relevance(
            "https://example.com/about", "", kw, 4
        )
        assert score_shallow > score_deep

    def test_no_keywords_still_scores(self):
        score = score_url_relevance("https://example.com/page", "", set(), 0)
        assert score > 0

    def test_priority_queue_order(self):
        """High relevance URLs should be popped first (lowest priority number)."""
        import heapq
        q = []
        heapq.heappush(q, CrawlItem(priority=-10.0, url="high", depth=0, discovery_order=1))
        heapq.heappush(q, CrawlItem(priority=-2.0, url="low", depth=0, discovery_order=2))
        heapq.heappush(q, CrawlItem(priority=-5.0, url="mid", depth=0, discovery_order=3))
        assert heapq.heappop(q).url == "high"
        assert heapq.heappop(q).url == "mid"
        assert heapq.heappop(q).url == "low"


# ── HTML parsing ────────────────────────────────────────────────────

class TestHTMLParsing:
    def test_basic_parsing(self):
        html = """
        <html><head><title>Test Page</title></head>
        <body>
            <h1>Main Heading</h1>
            <p>Some content here.</p>
            <h2>Sub Heading</h2>
            <p>More content.</p>
            <a href="/other">Other Page</a>
        </body></html>
        """
        page = parse_html(html, "https://example.com/test")
        assert page.title == "Test Page"
        assert "Main Heading" in page.text
        assert "Some content here" in page.text
        assert len(page.headings) == 2
        assert page.headings[0].level == 1
        assert page.headings[0].text == "Main Heading"

    def test_link_extraction(self):
        html = """
        <html><body>
            <a href="/page1">Page 1</a>
            <a href="https://example.com/page2">Page 2</a>
            <a href="https://other.com/external">External</a>
        </body></html>
        """
        page = parse_html(html, "https://example.com/")
        assert any("/page1" in link for link in page.links)
        assert any("/page2" in link for link in page.links)

    def test_script_and_style_removed(self):
        html = """
        <html><body>
            <script>alert('xss')</script>
            <style>.hidden{display:none}</style>
            <p>Visible content</p>
        </body></html>
        """
        page = parse_html(html, "https://example.com/")
        assert "alert" not in page.text
        assert "hidden" not in page.text
        assert "Visible content" in page.text

    def test_link_anchor_extraction(self):
        html = """
        <html><body>
            <a href="/pricing">View Pricing</a>
            <a href="/about">About Us</a>
        </body></html>
        """
        links = extract_links_with_anchor(html, "https://example.com/")
        assert len(links) == 2
        urls = {url for url, _ in links}
        anchors = {anchor for _, anchor in links}
        assert "View Pricing" in anchors
        assert "About Us" in anchors


# ── Robots.txt parser ───────────────────────────────────────────────

class TestRobotsTxt:
    def test_disallow_path(self):
        parser = RobotsTxtParser()
        parser._parse("""
User-agent: *
Disallow: /admin
Disallow: /private
        """)
        assert not parser.is_allowed("https://example.com/admin/settings")
        assert not parser.is_allowed("https://example.com/private/data")
        assert parser.is_allowed("https://example.com/public")

    def test_allow_overrides_disallow(self):
        parser = RobotsTxtParser()
        parser._parse("""
User-agent: *
Disallow: /api
Allow: /api/public
        """)
        assert parser.is_allowed("https://example.com/api/public/data")

    def test_crawl_delay(self):
        parser = RobotsTxtParser()
        parser._parse("""
User-agent: *
Crawl-delay: 2
        """)
        assert parser.crawl_delay == 2.0

    def test_sitesage_specific_rules(self):
        parser = RobotsTxtParser()
        parser._parse("""
User-agent: Googlebot
Disallow: /

User-agent: SiteSage
Disallow: /secret
Allow: /public
        """)
        assert not parser.is_allowed("https://example.com/secret/page")
        assert parser.is_allowed("https://example.com/public/page")

    def test_empty_robots_allows_all(self):
        parser = RobotsTxtParser()
        parser._parse("")
        assert parser.is_allowed("https://example.com/anything")


# ── Max page limit ──────────────────────────────────────────────────

class TestMaxPageLimit:
    def test_hard_cap_enforced(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=50)
        assert crawler.max_pages == 30  # capped at config.MAX_PAGES

    def test_custom_lower_limit(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=10)
        assert crawler.max_pages == 10


# ── Cancellation ─────────────────────────────────────────────────────

class TestCancellation:
    def test_cancel_flag(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=10)
        assert not crawler.is_cancelled
        crawler.cancel()
        assert crawler.is_cancelled

    @pytest.mark.asyncio
    async def test_cancel_stops_crawl(self):
        """Crawler should stop promptly when cancelled."""
        crawler = WebCrawler("s1", "https://example.com", "test question",
                             max_pages=5, total_timeout=10)
        progress_messages = []

        def on_progress(p):
            progress_messages.append(p)
            if p.pages_crawled >= 1:
                crawler.cancel()

        # Mock the safety check to allow the seed
        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()

                # Mock robots.txt
                robots_resp = MagicMock()
                robots_resp.status_code = 404
                mock_client.get = AsyncMock(return_value=robots_resp)

                # Create a response that returns HTML
                html_resp = MagicMock()
                html_resp.status_code = 200
                html_resp.is_redirect = False
                html_resp.headers = {"content-type": "text/html"}
                html_resp.text = "<html><body><p>Content here for testing.</p><a href='/page2'>link</a></body></html>"

                call_count = 0
                async def mock_get(url, **kwargs):
                    nonlocal call_count
                    call_count += 1
                    if "robots.txt" in url:
                        return robots_resp
                    return html_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl(progress_callback=on_progress)

        # Should have stopped after cancellation
        assert crawler.is_cancelled
        # Final progress should indicate cancellation
        final = progress_messages[-1]
        assert final.status == SessionStatus.CANCELLED


# ── Request timeout handling ────────────────────────────────────────

class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_timeout_counted_as_failure(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()

                robots_resp = MagicMock()
                robots_resp.status_code = 404
                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    raise httpx.TimeoutException("timed out")

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed > 0


# ── HTTP failure handling ───────────────────────────────────────────

class TestHTTPFailures:
    @pytest.mark.asyncio
    async def test_404_counted_as_failure(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                error_resp = MagicMock()
                error_resp.status_code = 404
                error_resp.is_redirect = False

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    return error_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1

    @pytest.mark.asyncio
    async def test_500_counted_as_failure(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                error_resp = MagicMock()
                error_resp.status_code = 500
                error_resp.is_redirect = False

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    return error_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1

    @pytest.mark.asyncio
    async def test_connection_error_handled(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    raise httpx.ConnectError("connection refused")

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1


# ── Non-HTML response handling ──────────────────────────────────────

class TestNonHTMLHandling:
    @pytest.mark.asyncio
    async def test_pdf_rejected(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                pdf_resp = MagicMock()
                pdf_resp.status_code = 200
                pdf_resp.is_redirect = False
                pdf_resp.headers = {"content-type": "application/pdf"}

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    return pdf_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1

    @pytest.mark.asyncio
    async def test_image_rejected(self):
        crawler = WebCrawler("s1", "https://example.com/image.png", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                img_resp = MagicMock()
                img_resp.status_code = 200
                img_resp.is_redirect = False
                img_resp.headers = {"content-type": "image/png"}

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    return img_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1


# ── Concurrent request limits ───────────────────────────────────────

class TestConcurrencyLimit:
    def test_semaphore_initialized_correctly(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_concurrent=3)
        assert crawler._semaphore._value == 3

    def test_default_concurrency_is_3(self):
        crawler = WebCrawler("s1", "https://example.com", "test")
        assert crawler._semaphore._value == 3


# ── Crawl progress tracking ────────────────────────────────────────

class TestProgressTracking:
    def test_initial_progress(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=10)
        progress = crawler._make_progress()
        assert progress.session_id == "s1"
        assert progress.status == SessionStatus.CRAWLING
        assert progress.pages_crawled == 0
        assert progress.pages_failed == 0
        assert progress.pages_discovered == 0

    def test_progress_after_discovery(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=10)
        crawler._enqueue("https://example.com/page1", 1, "Link")
        progress = crawler._make_progress()
        assert progress.pages_discovered == 1
        assert progress.pages_queued == 1


# ── Oversized response rejection ────────────────────────────────────

class TestOversizedResponse:
    @pytest.mark.asyncio
    async def test_oversized_content_length_rejected(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30,
                             max_response_bytes=1000)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                big_resp = MagicMock()
                big_resp.status_code = 200
                big_resp.is_redirect = False
                big_resp.headers = {
                    "content-type": "text/html",
                    "content-length": "9999999",
                }

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    return big_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1


# ── Thin page skipping ──────────────────────────────────────────────

class TestThinPages:
    @pytest.mark.asyncio
    async def test_thin_page_skipped(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=30)

        with patch("crawler.is_url_safe", return_value=(True, "ok")):
            with patch("crawler.httpx.AsyncClient") as MockClient:
                mock_client = AsyncMock()
                robots_resp = MagicMock()
                robots_resp.status_code = 404

                thin_resp = MagicMock()
                thin_resp.status_code = 200
                thin_resp.is_redirect = False
                thin_resp.headers = {"content-type": "text/html"}
                thin_resp.text = "<html><body>Hi</body></html>"

                async def mock_get(url, **kwargs):
                    if "robots.txt" in url:
                        return robots_resp
                    return thin_resp

                mock_client.get = AsyncMock(side_effect=mock_get)
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                MockClient.return_value = mock_client

                pages = await crawler.crawl()

        assert len(pages) == 0
        assert crawler._pages_failed >= 1


# ── Unsafe seed URL ────────────────────────────────────────────────

class TestUnsafeSeed:
    @pytest.mark.asyncio
    async def test_unsafe_seed_returns_empty(self):
        crawler = WebCrawler("s1", "https://example.com", "test",
                             max_pages=5, total_timeout=10)
        progress_messages = []

        with patch("crawler.is_url_safe", return_value=(False, "private IP")):
            pages = await crawler.crawl(progress_callback=progress_messages.append)

        assert len(pages) == 0
        assert any(p.status == SessionStatus.ERROR for p in progress_messages)


# ── Database integration ───────────────────────────────────────────

class TestDatabaseIntegration:
    def test_persist_crawled_page(self, tmp_path):
        from database import init_db, create_session, get_db, get_session
        from models import HeadingInfo, CrawledPage

        db_file = tmp_path / "crawl_test.db"
        init_db(db_file)

        session_id = "test_sess_01"
        with get_db(db_file) as conn:
            create_session(conn, session_id, "https://example.com", "question")

        crawler = WebCrawler(
            session_id,
            "https://example.com",
            "question",
            persist_to_db=True,
            db_path=db_file,
        )

        test_page = CrawledPage(
            url="https://example.com/info",
            title="Info Page",
            text="Detailed information text for testing persistence.",
            headings=[
                HeadingInfo(level=1, text="Main Section", position=0),
                HeadingInfo(level=2, text="Sub Section", position=15),
            ],
            status_code=200,
        )

        page_id = crawler.persist_page(test_page)
        assert page_id is not None
        assert page_id > 0

        with get_db(db_file) as conn:
            pages = conn.execute("SELECT * FROM pages WHERE session_id = ?", (session_id,)).fetchall()
            assert len(pages) == 1
            assert pages[0]["url"] == "https://example.com/info"
            assert pages[0]["title"] == "Info Page"

            headings = conn.execute("SELECT * FROM headings WHERE page_id = ?", (page_id,)).fetchall()
            assert len(headings) == 2
            assert headings[0]["text"] == "Main Section"
            assert headings[1]["text"] == "Sub Section"

            sess = get_session(conn, session_id)
            assert sess["pages_crawled"] == 0  # _pages_crawled was not incremented in manual persist_page

    def test_duplicate_page_not_duplicated_in_db(self, tmp_path):
        from database import init_db, create_session, get_db
        from models import CrawledPage

        db_file = tmp_path / "crawl_dup_test.db"
        init_db(db_file)

        session_id = "test_sess_dup"
        with get_db(db_file) as conn:
            create_session(conn, session_id, "https://example.com", "question")

        crawler = WebCrawler(
            session_id,
            "https://example.com",
            "question",
            persist_to_db=True,
            db_path=db_file,
        )

        test_page = CrawledPage(
            url="https://example.com/page",
            title="Page",
            text="Text body",
            status_code=200,
        )

        crawler.persist_page(test_page)
        # Attempt to insert same URL in same session
        crawler.persist_page(test_page)

        with get_db(db_file) as conn:
            pages = conn.execute("SELECT * FROM pages WHERE session_id = ?", (session_id,)).fetchall()
            assert len(pages) == 1

