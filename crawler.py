"""
SiteSage — Smart website crawler (Phase 2).

Question-aware priority crawler that:
- Crawls up to MAX_PAGES successfully-fetched HTML pages
- Restricts to the seed URL's origin
- Scores links by relevance to the user's question
- Provides real-time progress updates
- Handles SSRF, redirects, timeouts, cancellation, robots.txt
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

import httpx
from bs4 import BeautifulSoup

import config
import database
from models import CrawlProgress, CrawledPage, HeadingInfo, SessionStatus

logger = logging.getLogger(__name__)

# ── URL normalization & safety ───────────────────────────────────────

ALLOWED_SCHEMES = {"http", "https"}


def normalize_url(raw_url: str) -> str:
    """Normalize a URL: lowercase scheme/host, strip fragments and
    tracking params, sort remaining query params, collapse path.

    Preserves meaningful query parameters while removing known trackers.
    """
    raw_url = raw_url.strip()
    parsed = urlparse(raw_url)

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        return ""

    hostname = parsed.hostname or ""
    hostname = hostname.lower().rstrip(".")

    # Reconstruct port only if non-default
    port = parsed.port
    if port and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port = None
    netloc = hostname if not port else f"{hostname}:{port}"

    # Normalize path: resolve .. and ., collapse //
    path = parsed.path or "/"
    # Decode percent-encoded chars that don't need encoding, re-encode
    path = quote(unquote(path), safe="/:@!$&'()*+,;=-._~")
    # Collapse consecutive slashes
    path = re.sub(r"/+", "/", path)
    # Remove trailing slash except for root
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # Strip tracking params, keep meaningful ones, sort
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {
        k: v
        for k, v in query_params.items()
        if k.lower() not in config.TRACKING_PARAMS
    }
    sorted_query = urlencode(filtered, doseq=True) if filtered else ""

    # Drop fragment entirely
    return urlunparse((scheme, netloc, path, "", sorted_query, ""))


def get_origin(url: str) -> str:
    """Extract scheme + host (+ non-default port) = the 'origin'."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    port = parsed.port
    if port and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        port = None
    if port:
        return f"{scheme}://{hostname}:{port}"
    return f"{scheme}://{hostname}"


def is_same_origin(url: str, origin: str) -> bool:
    """Check if url belongs to the given origin."""
    return get_origin(url) == origin


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address string falls in blocked private/loopback/link-local ranges."""
    for prefix in config.BLOCKED_IP_PREFIXES:
        if ip_str.startswith(prefix):
            return True
    return False


def is_blocked_port(url: str) -> bool:
    """Check if the URL targets a blocked port."""
    parsed = urlparse(url)
    port = parsed.port
    if port and port in config.BLOCKED_PORTS:
        return True
    return False


def validate_host_dns(hostname: str) -> tuple[bool, str]:
    """Resolve hostname and check that it doesn't point to a private IP.

    Returns (is_safe, resolved_ip_or_error_message).
    """
    if not hostname:
        return False, "empty hostname"
    try:
        # Resolve to check for private IPs (SSRF / DNS rebinding defense)
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in infos:
            ip = sockaddr[0]
            if is_private_ip(ip):
                return False, f"private IP {ip}"
        if not infos:
            return False, "no DNS records"
        return True, infos[0][4][0]
    except (socket.gaierror, OSError) as e:
        return False, f"DNS resolution failed: {e}"


def is_url_safe(url: str, allowed_origin: str) -> tuple[bool, str]:
    """Combined safety check: scheme, origin, port, DNS.

    Returns (is_safe, reason_if_unsafe).
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False, f"blocked scheme: {parsed.scheme}"

    if is_blocked_port(url):
        return False, f"blocked port: {parsed.port}"

    if not is_same_origin(url, allowed_origin):
        return False, "different origin"

    hostname = parsed.hostname or ""
    safe, detail = validate_host_dns(hostname)
    if not safe:
        return False, f"unsafe host: {detail}"

    return True, "ok"


# ── Robots.txt parser (simple, no external deps) ────────────────────

class RobotsTxtParser:
    """Minimal robots.txt parser for a single user-agent."""

    def __init__(self) -> None:
        self.disallowed: list[str] = []
        self.allowed: list[str] = []
        self.crawl_delay: Optional[float] = None
        self._loaded = False

    async def load(self, client: httpx.AsyncClient, origin: str) -> None:
        """Fetch and parse robots.txt from the origin."""
        try:
            resp = await client.get(
                f"{origin}/robots.txt",
                timeout=5.0,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                self._parse(resp.text)
            # If 404 or other error, everything is allowed
        except (httpx.HTTPError, Exception):
            pass  # On failure, allow everything
        self._loaded = True

    def _parse(self, text: str) -> None:
        """Parse robots.txt rules for * and our user-agent."""
        in_relevant_block = False
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if ":" not in line:
                continue
            field_name, _, value = line.partition(":")
            field_name = field_name.strip().lower()
            value = value.strip()

            if field_name == "user-agent":
                agent = value.lower()
                in_relevant_block = agent in ("*", "sitesage")
                continue

            if not in_relevant_block:
                continue

            if field_name == "disallow" and value:
                self.disallowed.append(value)
            elif field_name == "allow" and value:
                self.allowed.append(value)
            elif field_name == "crawl-delay":
                try:
                    self.crawl_delay = float(value)
                except ValueError:
                    pass

    def is_allowed(self, url: str) -> bool:
        """Check if url path is allowed by robots.txt rules."""
        path = urlparse(url).path or "/"

        # Check explicit allows first (more specific wins)
        for pattern in self.allowed:
            if path.startswith(pattern):
                return True

        for pattern in self.disallowed:
            if pattern == "/" and not any(path.startswith(a) for a in self.allowed):
                return False
            if path.startswith(pattern):
                return False

        return True


# ── Question-aware link priority scoring ─────────────────────────────

def extract_query_keywords(question: str) -> set[str]:
    """Extract meaningful keywords from the user's question for priority scoring."""
    # Basic stopword list
    stopwords = {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "shall", "can", "need", "must",
        "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us",
        "my", "your", "his", "its", "our", "their",
        "this", "that", "these", "those",
        "what", "which", "who", "whom", "whose", "when", "where", "why", "how",
        "not", "no", "nor", "so", "if", "or", "and", "but", "for", "with",
        "at", "by", "to", "in", "on", "of", "from", "up", "about", "into",
        "through", "during", "before", "after", "above", "below", "between",
        "out", "off", "over", "under", "again", "further", "then", "than",
        "very", "just", "also", "any", "each", "few", "more", "most", "some",
        "such", "only", "own", "same", "too", "here", "there",
    }
    words = re.findall(r"[a-zA-Z0-9]+", question.lower())
    return {w for w in words if w not in stopwords and len(w) > 1}


def score_url_relevance(
    url: str,
    anchor_text: str,
    keywords: set[str],
    depth: int,
) -> float:
    """Score a discovered URL's relevance to the user's question.

    Higher score = higher priority (fetched sooner).
    Components:
    - URL path keyword match
    - Anchor text keyword match
    - Depth penalty (shallower = better)
    """
    if not keywords:
        # No keywords → score by depth only
        return max(0.0, 10.0 - depth * 2.0)

    score = 0.0

    # URL path match
    path_lower = urlparse(url).path.lower().replace("-", " ").replace("_", " ")
    path_words = set(re.findall(r"[a-z0-9]+", path_lower))
    path_overlap = len(keywords & path_words)
    score += path_overlap * 3.0

    # Anchor text match
    if anchor_text:
        anchor_lower = anchor_text.lower()
        anchor_words = set(re.findall(r"[a-z0-9]+", anchor_lower))
        anchor_overlap = len(keywords & anchor_words)
        score += anchor_overlap * 4.0

    # Depth penalty
    score += max(0.0, 5.0 - depth * 1.0)

    return score


# ── Priority queue item ──────────────────────────────────────────────

@dataclass(order=True)
class CrawlItem:
    """Item in the priority queue. Lower priority number = fetched first.
    We negate relevance score so heapq (min-heap) pops highest score first.
    """
    priority: float
    url: str = field(compare=False)
    depth: int = field(compare=False)
    anchor_text: str = field(compare=False, default="")
    discovery_order: int = field(compare=False, default=0)


# ── HTML parsing ─────────────────────────────────────────────────────

def parse_html(html: str, base_url: str) -> CrawledPage:
    """Parse HTML into a CrawledPage with title, clean text, headings, links."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script, style, nav, footer, header noise
    for tag in soup.find_all(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    # Title
    title = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        title = title_tag.string.strip()

    # Headings
    headings: list[HeadingInfo] = []
    text_parts: list[str] = []
    char_offset = 0

    # Walk the body for text and headings
    body = soup.find("body") or soup
    for element in body.descendants:
        if element.name and element.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            heading_text = element.get_text(strip=True)
            if heading_text:
                level = int(element.name[1])
                headings.append(HeadingInfo(
                    level=level,
                    text=heading_text,
                    position=char_offset,
                ))
        if hasattr(element, "string") and element.string and element.parent.name not in (
            "script", "style", "noscript",
        ):
            text = element.string.strip()
            if text:
                text_parts.append(text)
                char_offset += len(text) + 1  # +1 for space

    cleaned_text = " ".join(text_parts)
    # Collapse whitespace
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()

    # Extract links with anchor text
    links: list[str] = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        try:
            absolute = urljoin(base_url, href)
            normalized = normalize_url(absolute)
            if normalized:
                links.append(normalized)
        except Exception:
            continue

    return CrawledPage(
        url=base_url,
        title=title,
        text=cleaned_text,
        headings=headings,
        links=links,
        status_code=200,
    )


def extract_links_with_anchor(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract (normalized_url, anchor_text) pairs from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        anchor = a_tag.get_text(strip=True) or ""
        try:
            absolute = urljoin(base_url, href)
            normalized = normalize_url(absolute)
            if normalized:
                results.append((normalized, anchor))
        except Exception:
            continue
    return results


# ── Crawler engine ───────────────────────────────────────────────────

ProgressCallback = Callable[[CrawlProgress], None]


class WebCrawler:
    """Async question-aware priority crawler.

    Usage:
        crawler = WebCrawler(session_id, seed_url, question)
        pages = await crawler.crawl(progress_callback=my_callback)
    """

    def __init__(
        self,
        session_id: str,
        seed_url: str,
        question: str,
        *,
        max_pages: int = config.MAX_PAGES,
        max_depth: int = config.MAX_CRAWL_DEPTH,
        timeout_per_page: float = config.CRAWL_TIMEOUT_PER_PAGE,
        total_timeout: float = config.CRAWL_TOTAL_TIMEOUT,
        max_concurrent: int = config.MAX_CONCURRENT_REQUESTS,
        max_response_bytes: int = config.MAX_RESPONSE_BYTES,
        crawl_delay: float = config.CRAWL_DELAY,
        persist_to_db: bool = False,
        db_path: Path | str = config.DB_PATH,
    ):
        self.session_id = session_id
        self.seed_url = normalize_url(seed_url)
        self.question = question
        self.origin = get_origin(self.seed_url)
        self.keywords = extract_query_keywords(question)
        self.persist_to_db = persist_to_db
        self.db_path = db_path

        # Limits
        self.max_pages = min(max_pages, config.MAX_PAGES)  # hard cap
        self.max_depth = max_depth
        self.timeout_per_page = timeout_per_page
        self.total_timeout = total_timeout
        self.max_concurrent = max_concurrent
        self.max_response_bytes = max_response_bytes
        self.crawl_delay = crawl_delay

        # State
        self._seen_urls: set[str] = set()
        self._queue: list[CrawlItem] = []  # min-heap
        self._discovery_counter: int = 0
        self._pages_crawled: int = 0
        self._pages_failed: int = 0
        self._pages_discovered: int = 0
        self._results: list[CrawledPage] = []
        self._cancelled = False
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._robots: RobotsTxtParser = RobotsTxtParser()
        self._last_request_time: float = 0.0
        self._start_time: float = 0.0

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        """Signal the crawler to stop after current in-flight requests."""
        self._cancelled = True

    def persist_page(self, page: CrawledPage) -> Optional[int]:
        """Persist a single crawled page and its headings into the database using transactions."""
        try:
            with database.get_db(self.db_path) as conn:
                sess = database.get_session(conn, self.session_id)
                if not sess:
                    return None
                page_id = database.insert_page(
                    conn,
                    self.session_id,
                    page.url,
                    page.title,
                    page.text,
                    page.crawl_depth,
                    page.status_code,
                )
                if page_id:
                    for h in page.headings:
                        database.insert_heading(conn, page_id, h.level, h.text, h.position)
                database.update_session_status(
                    conn,
                    self.session_id,
                    status=SessionStatus.CRAWLING.value,
                    pages_discovered=self._pages_discovered,
                    pages_queued=len(self._queue),
                    pages_crawled=self._pages_crawled,
                    pages_failed=self._pages_failed,
                )
                return page_id
        except Exception as e:
            logger.warning("Failed to persist page %s to database: %s", page.url, e)
            return None

    def _make_progress(
        self,
        status: SessionStatus = SessionStatus.CRAWLING,
        current_url: Optional[str] = None,
        message: Optional[str] = None,
    ) -> CrawlProgress:
        return CrawlProgress(
            session_id=self.session_id,
            status=status,
            pages_discovered=self._pages_discovered,
            pages_queued=len(self._queue),
            pages_crawled=self._pages_crawled,
            pages_failed=self._pages_failed,
            current_url=current_url,
            message=message,
        )

    def _enqueue(self, url: str, depth: int, anchor_text: str = "") -> bool:
        """Add url to the priority queue if not seen and within limits."""
        if url in self._seen_urls:
            return False
        if depth > self.max_depth:
            return False

        self._seen_urls.add(url)
        self._pages_discovered += 1
        self._discovery_counter += 1

        relevance = score_url_relevance(url, anchor_text, self.keywords, depth)
        # Negate for min-heap (highest relevance = lowest priority number)
        # Use discovery_order as tiebreaker
        item = CrawlItem(
            priority=-relevance,
            url=url,
            depth=depth,
            anchor_text=anchor_text,
            discovery_order=self._discovery_counter,
        )
        heapq.heappush(self._queue, item)
        return True

    def _time_remaining(self) -> float:
        return max(0.0, self.total_timeout - (time.monotonic() - self._start_time))

    async def _respect_delay(self) -> None:
        """Enforce per-host crawl delay."""
        delay = self.crawl_delay
        if self._robots.crawl_delay:
            delay = max(delay, self._robots.crawl_delay)
        elapsed_since_last = time.monotonic() - self._last_request_time
        wait = delay - elapsed_since_last
        if wait > 0:
            await asyncio.sleep(wait)

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        item: CrawlItem,
    ) -> Optional[CrawledPage]:
        """Fetch a single page with all safety checks."""
        url = item.url

        # Check robots.txt
        if not self._robots.is_allowed(url):
            logger.info("Blocked by robots.txt: %s", url)
            self._pages_failed += 1
            return None

        async with self._semaphore:
            if self._cancelled:
                return None

            await self._respect_delay()
            self._last_request_time = time.monotonic()

            remaining = self._time_remaining()
            if remaining <= 0:
                return None

            timeout = min(self.timeout_per_page, remaining)

            try:
                resp = await client.get(
                    url,
                    timeout=timeout,
                    follow_redirects=False,  # handle redirects manually
                )

                # Handle redirects manually for safety
                redirect_count = 0
                while resp.is_redirect and redirect_count < config.MAX_REDIRECTS:
                    redirect_count += 1
                    location = resp.headers.get("location", "")
                    if not location:
                        break
                    target_url = urljoin(url, location)
                    redirect_url = normalize_url(target_url)
                    if not redirect_url:
                        logger.info("Invalid redirect from %s to %s", url, location)
                        self._pages_failed += 1
                        return None

                    # Validate redirect destination
                    safe, reason = is_url_safe(redirect_url, self.origin)
                    if not safe:
                        logger.info("Unsafe redirect from %s: %s", url, reason)
                        self._pages_failed += 1
                        return None

                    # If the redirect location explicitly had a trailing slash, preserve it for the fetch
                    fetch_url = target_url if target_url.endswith("/") and not redirect_url.endswith("/") else redirect_url
                    resp = await client.get(
                        fetch_url,
                        timeout=timeout,
                        follow_redirects=False,
                    )
                    url = redirect_url

                # Check status
                if resp.status_code == 429:
                    logger.info("Rate limited at %s", url)
                    self._pages_failed += 1
                    return None

                if resp.status_code >= 400:
                    logger.info("HTTP %d at %s", resp.status_code, url)
                    self._pages_failed += 1
                    return None

                # Check content type
                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type.lower() and "application/xhtml" not in content_type.lower():
                    logger.info("Non-HTML content at %s: %s", url, content_type)
                    self._pages_failed += 1
                    return None

                # Check response size
                content_length = resp.headers.get("content-length")
                if content_length and int(content_length) > self.max_response_bytes:
                    logger.info("Oversized response at %s: %s bytes", url, content_length)
                    self._pages_failed += 1
                    return None

                html = resp.text
                if len(html.encode("utf-8", errors="replace")) > self.max_response_bytes:
                    logger.info("Response body too large at %s", url)
                    self._pages_failed += 1
                    return None

                # Parse
                page = parse_html(html, url)
                page.crawl_depth = item.depth
                page.status_code = resp.status_code

                # Skip pages with too little text
                if len(page.text) < config.MIN_PAGE_TEXT_LENGTH:
                    logger.info("Skipping thin page %s (%d chars)", url, len(page.text))
                    self._pages_failed += 1
                    return None

                # Discover links from this page
                link_anchors = extract_links_with_anchor(html, url)
                for link_url, anchor in link_anchors:
                    if is_same_origin(link_url, self.origin):
                        self._enqueue(link_url, item.depth + 1, anchor)

                return page

            except httpx.TimeoutException:
                logger.info("Timeout fetching %s", url)
                self._pages_failed += 1
                return None
            except httpx.HTTPError as e:
                logger.info("HTTP error fetching %s: %s", url, e)
                self._pages_failed += 1
                return None
            except Exception as e:
                logger.info("Unexpected error fetching %s: %s", url, e)
                self._pages_failed += 1
                return None

    async def crawl(
        self,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> list[CrawledPage]:
        """Execute the crawl. Returns list of successfully crawled pages."""
        self._start_time = time.monotonic()

        # Validate seed URL safety
        safe, reason = is_url_safe(self.seed_url, self.origin)
        if not safe:
            if progress_callback:
                progress_callback(self._make_progress(
                    status=SessionStatus.ERROR,
                    message=f"Seed URL is unsafe: {reason}",
                ))
            return []

        # Enqueue seed
        self._enqueue(self.seed_url, depth=0)

        if progress_callback:
            progress_callback(self._make_progress(
                message="Starting crawl...",
            ))

        async with httpx.AsyncClient(
            headers={"User-Agent": config.USER_AGENT},
            follow_redirects=False,
            max_redirects=0,
        ) as client:
            # Load robots.txt
            try:
                await self._robots.load(client, self.origin)
            except Exception:
                pass  # If robots.txt fails, allow everything

            # Main crawl loop
            while (
                self._queue
                and self._pages_crawled < self.max_pages
                and not self._cancelled
                and self._time_remaining() > 0
            ):
                item = heapq.heappop(self._queue)

                if progress_callback:
                    progress_callback(self._make_progress(
                        current_url=item.url,
                        message=f"Fetching: {item.url}",
                    ))

                page = await self._fetch_page(client, item)
                if page:
                    self._pages_crawled += 1
                    self._results.append(page)

                    if self.persist_to_db:
                        self.persist_page(page)

                    if progress_callback:
                        progress_callback(self._make_progress(
                            current_url=item.url,
                            message=f"Crawled ({self._pages_crawled}/{self.max_pages}): {item.url}",
                        ))

        # Final status
        if self._cancelled:
            final_status = SessionStatus.CANCELLED
            final_msg = f"Crawl cancelled. {self._pages_crawled} pages collected."
        elif self._pages_crawled == 0:
            final_status = SessionStatus.ERROR
            final_msg = "No pages could be crawled."
        else:
            final_status = SessionStatus.DONE
            final_msg = f"Crawl complete. {self._pages_crawled} pages collected."

        if self.persist_to_db:
            try:
                with database.get_db(self.db_path) as conn:
                    if database.get_session(conn, self.session_id):
                        database.update_session_status(
                            conn,
                            self.session_id,
                            status=final_status.value,
                            pages_discovered=self._pages_discovered,
                            pages_queued=len(self._queue),
                            pages_crawled=self._pages_crawled,
                            pages_failed=self._pages_failed,
                        )
            except Exception as e:
                logger.warning("Failed to update final session status in DB: %s", e)

        if progress_callback:
            progress_callback(self._make_progress(
                status=final_status,
                message=final_msg,
            ))

        return self._results
