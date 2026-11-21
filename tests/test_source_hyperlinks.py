"""
Integration and regression test for clickable source hyperlinks and safe DOM construction.

Runs the frontend test suite under Node.js and tests backend citation preservation.
"""

import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def test_node_source_hyperlinks_suite():
    """Execute the Node.js source hyperlinks test suite."""
    test_file = BASE_DIR / "tests" / "test_source_hyperlinks.js"
    assert test_file.exists(), f"Test script {test_file} not found"

    res = subprocess.run(
        ["node", str(test_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, f"Node test suite failed:\n{res.stdout}\n{res.stderr}"
    assert "PASSED CLEANLY (100% OK)" in res.stdout


def test_backend_claim_sources_traceability():
    """Verify that backend models preserve structured source references."""
    from models import ClaimEvidence, SearchResult, SourceReference

    src1 = SourceReference(
        page_url="https://example.com/pricing?ref=promo&tier=1#features",
        page_title="Pricing & Plans",
        passage_id=1,
        section_heading="Tiers",
        exact_quote="The Starter plan costs $19 per month.",
    )
    src2 = SourceReference(
        page_url="https://example.com/item/Special%20Edition%20(2026)",
        page_title="Special Edition",
        passage_id=2,
        section_heading="Overview",
        exact_quote="Special Edition includes bonus storage.",
    )

    claim = ClaimEvidence(
        claim="The Starter plan costs $19 per month with bonus storage.",
        confidence=0.88,
        aspect="Pricing and Features",
        sources=[src1, src2],
    )

    result = SearchResult(
        answer=(
            "The Starter plan costs $19 per month [Source: https://example.com/pricing?ref=promo&tier=1#features]. "
            "Special Edition includes bonus storage [Source: https://example.com/item/Special%20Edition%20(2026)]."
        ),
        claims=[claim],
    )

    assert len(result.claims) == 1
    assert len(result.claims[0].sources) == 2
    assert result.claims[0].sources[0].page_url == "https://example.com/pricing?ref=promo&tier=1#features"
    assert result.claims[0].sources[1].page_url == "https://example.com/item/Special%20Edition%20(2026)"
