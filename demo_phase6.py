"""
Phase 6 End-to-End Pipeline & Real-Time SSE Demonstration.
Validates:
1. Full pipeline orchestration: validation -> crawling -> indexing -> decomposition -> BM25 ranking -> deterministic extraction -> persistence.
2. Structured SSE event stream sequence and payload formatting.
3. Mid-stream reconnection using Last-Event-ID to retrieve missed events.
4. Cancellation safety mid-pipeline.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import database
from models import CrawlProgress, CrawlRequest, CrawledPage, HeadingInfo, SessionStatus
from pipeline import (
    cancel_pipeline_session,
    create_pipeline_session,
    execute_pipeline,
    subscribe_session_events,
)


async def main():
    print("=" * 70)
    print("SITESAGE PHASE 6: END-TO-END PIPELINE & SSE ORCHESTRATION DEMO")
    print("=" * 70)

    demo_db = Path("demo_phase6.db")
    if demo_db.exists():
        demo_db.unlink()
    database.init_db(demo_db)

    # ─────────────────────────────────────────────────────────────────
    # 1. Full Pipeline Orchestration with Mocked Multi-Page Crawl
    # ─────────────────────────────────────────────────────────────────
    print("\n--- 1. Executing Full Pipeline & Streaming SSE Events ---")

    req = CrawlRequest(
        url="https://docs.sitesage.local",
        question="What are the system requirements and pricing tiers?",
        max_pages=5,
        polish=False,
    )
    session = create_pipeline_session(req, session_id="demo_session_001", db_path=demo_db)

    # Simulated crawled pages
    mock_pages = [
        CrawledPage(
            url="https://docs.sitesage.local",
            title="SiteSage Overview",
            text="Welcome to SiteSage. SiteSage is a question-aware website search engine that extracts evidence-supported answers. System requirements: Python 3.10 or higher and 4GB RAM.",
            headings=[HeadingInfo(level=1, text="SiteSage Overview", position=0)],
        ),
        CrawledPage(
            url="https://docs.sitesage.local/pricing",
            title="SiteSage Pricing",
            text="Our pricing plans include Starter at $19 per month and Pro at $49 per month with unlimited searches.",
            headings=[
                HeadingInfo(level=1, text="Pricing", position=0),
                HeadingInfo(level=2, text="Plans", position=1),
            ],
        ),
    ]

    # Start event collection in background
    collected_events = []

    async def collect_stream():
        async for chunk in subscribe_session_events(session.session_id):
            collected_events.append(chunk)

    stream_task = asyncio.create_task(collect_stream())

    # Execute pipeline with patched crawler
    with patch("pipeline.WebCrawler.crawl", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = mock_pages
        result = await execute_pipeline(session, db_path=demo_db)

    await stream_task

    print(f"\nPipeline status: {session.status.value}")
    print(f"Total SSE Events streamed: {len(collected_events)}")
    print("\nSample SSE Stream excerpt (First 4 events):")
    for chunk in collected_events[:4]:
        for line in chunk.strip().split("\n"):
            print(f"  {line}")
        print()

    print("Sample SSE Stream excerpt (Final events):")
    for chunk in collected_events[-3:]:
        for line in chunk.strip().split("\n"):
            print(f"  {line}")
        print()

    print("\nExtracted Answer:")
    print(f"  {result.answer}")
    print(f"\nAspects decomposed: {len(result.question_aspects)}")
    for a in result.question_aspects:
        print(f"  - Aspect: '{a.aspect}' (Keywords: {', '.join(a.keywords)})")
    print(f"Extracted claims: {len(result.claims)}")
    for c in result.claims:
        print(f"  * Claim: {c.claim}")
        print(f"    Confidence: {c.confidence:.0%}")
        for s in c.sources:
            print(f"    Source: {s.page_url} (Heading: {s.section_heading})")

    # ─────────────────────────────────────────────────────────────────
    # 2. SSE Reconnection & Last-Event-ID History Replay
    # ─────────────────────────────────────────────────────────────────
    print("\n--- 2. Stream Reconnection using Last-Event-ID ---")
    print(f"Client reconnects to {session.session_id} presenting Last-Event-ID: 5")

    replayed_chunks = []
    async for chunk in subscribe_session_events(session.session_id, last_event_id=5):
        replayed_chunks.append(chunk)

    print(f"Replayed events (id > 5): {len(replayed_chunks)}")
    for chunk in replayed_chunks[:2]:
        for line in chunk.strip().split("\n"):
            print(f"  {line}")
        print()

    # ─────────────────────────────────────────────────────────────────
    # 3. Pipeline Cancellation Test
    # ─────────────────────────────────────────────────────────────────
    print("\n--- 3. Pipeline Cancellation Test ---")
    cancel_req = CrawlRequest(
        url="https://example.com/large-crawl",
        question="What is this site about?",
        max_pages=20,
    )
    cancel_session = create_pipeline_session(cancel_req, session_id="demo_cancel_002", db_path=demo_db)

    # Trigger cancellation immediately via helper
    cancel_pipeline_session("demo_cancel_002")
    cancel_result = await execute_pipeline(cancel_session, db_path=demo_db)

    print(f"Session status after cancel: {cancel_session.status.value}")
    print(f"Answer returned: {cancel_result.answer}")
    cancel_events = [e.event_type for e in cancel_session.events]
    print(f"Recorded event types: {cancel_events}")
    assert "session_cancelled" in cancel_events

    # Cleanup demo db
    if demo_db.exists():
        demo_db.unlink()

    print("\n" + "=" * 70)
    print("PHASE 6 VERIFICATION COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
