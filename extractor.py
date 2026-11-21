"""
SiteSage — Deterministic Evidence Extraction & Multi-Aspect Reasoning (Phase 4).

Features:
1. Deterministic Question Decomposition: splits compound questions into independent
   searchable aspects while leaving simple questions intact.
2. Aspect-Specific Evidence Retrieval & Deduplication: queries BM25 ranker,
   deduplicates overlapping passages, and tracks multi-page sources.
3. Claim-Level Extraction & Source Traceability: maps each extracted claim to its
   exact supporting passage, page URL, and heading context.
4. Transparent Confidence Signals: computed from BM25 score, keyword coverage, and
   cross-source agreement (not presented as calibrated probabilities).
5. Conflict & Missing Information Detection: flags contradictory statements and
   explicitly reports unanswered aspects.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

import config
from indexer import tokenize_text
from models import (
    ClaimEvidence,
    ConflictReport,
    QuestionAspect,
    ScoredPassage,
    SearchResult,
    SourceReference,
)
from ranker import BM25Ranker

logger = logging.getLogger(__name__)

# Idiomatic phrases containing "and" that should NOT be split
COMPOUND_IDIOMS = {
    "terms and conditions", "terms and privacy", "privacy and security",
    "tips and tricks", "pros and cons", "rock and roll", "health and safety",
    "trial and error", "q&a", "research and development", "r&d",
    "facts and figures", "questions and answers", "rules and regulations",
    "dos and don'ts", "bread and butter", "bits and pieces",
}


# ── 1. Question Decomposition ────────────────────────────────────────

def decompose_question(question: str) -> list[QuestionAspect]:
    """Deterministically analyze and decompose a question into searchable aspects.

    Simple questions remain as a single aspect.
    Compound questions are split along clausal conjunctions or punctuation.
    """
    cleaned_q = question.strip()
    if not cleaned_q:
        return []

    # Check for multiple sentence/question boundaries
    # E.g. "What is X? What is Y?" or "What is X; what is Y?"
    raw_subclauses: list[str] = []
    punct_split = re.split(r"[?;]+\s*", cleaned_q)
    punct_parts = [p.strip() for p in punct_split if len(p.strip()) > 3]

    if len(punct_parts) > 1:
        raw_subclauses = punct_parts
    else:
        # Check for clausal conjunctions: ", and ", ", as well as ", ", but "
        clause_split = re.split(
            r",\s*(?:and|as well as|along with|plus|but|while)\s+",
            cleaned_q,
            flags=re.IGNORECASE,
        )
        if len(clause_split) > 1:
            raw_subclauses = [p.strip() for p in clause_split if len(p.strip()) > 3]
        else:
            # Check for contrast: "difference between X and Y", "X compared to Y", "X vs Y"
            vs_match = re.search(r"\b(.+?)\s+(?:vs\.?|versus|compared to)\s+(.+)", cleaned_q, re.IGNORECASE)
            diff_match = re.search(r"difference between\s+(.+?)\s+and\s+(.+)", cleaned_q, re.IGNORECASE)

            if diff_match:
                entity_a = diff_match.group(1).strip()
                entity_b = diff_match.group(2).strip().rstrip("?.")
                raw_subclauses = [entity_a, entity_b, f"difference between {entity_a} and {entity_b}"]
            elif vs_match:
                entity_a = vs_match.group(1).strip()
                entity_b = vs_match.group(2).strip().rstrip("?.")
                raw_subclauses = [entity_a, entity_b, f"comparison between {entity_a} and {entity_b}"]
            else:
                # Check for " and " separating two full verb phrases / clauses
                # Avoid splitting known idioms like "terms and conditions"
                is_idiom = any(idiom in cleaned_q.lower() for idiom in COMPOUND_IDIOMS)
                if not is_idiom and " and " in cleaned_q.lower():
                    parts = re.split(r"\s+and\s+", cleaned_q, flags=re.IGNORECASE)
                    # Only split if both parts look like distinct requests (have > 2 tokens and question or subject words)
                    valid_parts = []
                    for part in parts:
                        tokens = tokenize_text(part, remove_stopwords=True)
                        if len(tokens) >= 2:
                            valid_parts.append(part.strip().rstrip("?.,"))

                    if len(valid_parts) >= 2:
                        raw_subclauses = valid_parts
                    else:
                        raw_subclauses = [cleaned_q]
                else:
                    raw_subclauses = [cleaned_q]

    aspects: list[QuestionAspect] = []
    seen_texts: set[str] = set()

    for sub in raw_subclauses:
        sub_clean = sub.strip().rstrip("?.,")
        if not sub_clean or sub_clean.lower() in seen_texts:
            continue
        seen_texts.add(sub_clean.lower())

        keywords = tokenize_text(sub_clean, remove_stopwords=True)
        if keywords:
            aspects.append(
                QuestionAspect(
                    aspect=sub_clean,
                    keywords=keywords,
                )
            )

    # Fallback to entire question if nothing extracted
    if not aspects:
        kw = tokenize_text(cleaned_q, remove_stopwords=True)
        aspects.append(QuestionAspect(aspect=cleaned_q, keywords=kw))

    return aspects[: config.MAX_ASPECTS]


# ── 2. Evidence Retrieval & Deduplication ────────────────────────────

def calculate_jaccard_similarity(text_a: str, text_b: str) -> float:
    """Calculate token-level Jaccard similarity between two texts."""
    tokens_a = set(tokenize_text(text_a, remove_stopwords=True))
    tokens_b = set(tokenize_text(text_b, remove_stopwords=True))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def retrieve_aspect_evidence(
    session_id: str,
    aspects: list[QuestionAspect],
    db_path: Path | str = config.DB_PATH,
    top_k_per_aspect: int = 5,
) -> tuple[dict[str, list[ScoredPassage]], list[ScoredPassage]]:
    """Retrieve ranked candidate passages for each question aspect using BM25.

    Deduplicates near-identical passages and returns:
    (aspect_evidence_map, all_unique_evidence).
    """
    ranker = BM25Ranker(db_path=db_path)
    aspect_evidence: dict[str, list[ScoredPassage]] = {}
    all_unique: list[ScoredPassage] = []

    for aspect in aspects:
        # Search using both full aspect text and key keywords
        query = " ".join(aspect.keywords) if aspect.keywords else aspect.aspect
        raw_results = ranker.rank_passages(session_id, query, top_k=top_k_per_aspect * 2)

        filtered: list[ScoredPassage] = []
        for scored in raw_results:
            if scored.score_breakdown.total_score < config.MIN_EVIDENCE_SCORE:
                continue

            # Check similarity with already selected passages for this aspect
            is_dup = False
            for existing in filtered:
                if calculate_jaccard_similarity(scored.passage.text, existing.passage.text) > 0.75:
                    is_dup = True
                    break

            if not is_dup:
                filtered.append(scored)
                if len(filtered) >= top_k_per_aspect:
                    break

        aspect_evidence[aspect.aspect] = filtered

        # Add to global unique list
        for f in filtered:
            if not any(f.passage.id == u.passage.id for u in all_unique):
                all_unique.append(f)

    return aspect_evidence, all_unique


# ── 3. Claim Extraction & Evidence Traceability ─────────────────────

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")

COMMON_TIER_MODIFIERS = {
    "basic", "starter", "business", "pro", "professional", "enterprise",
    "free", "premium", "standard", "ultimate", "personal", "team", "individual",
}

INTENT_COST_WORDS = {"cost", "costs", "price", "prices", "pricing", "rate", "rates", "fee", "fees"}

GENERIC_CATEGORY_WORDS = {
    "tier", "tiers", "plan", "plans", "subscription", "subscriptions",
    "option", "options", "level", "levels", "edition", "editions",
    "package", "packages", "cost", "costs", "price", "prices", "pricing",
    "rate", "rates", "fee", "fees", "feature", "features", "include", "included",
    "includes", "detail", "details", "info", "information",
}


def extract_claims_from_passage(
    passage: ScoredPassage,
    aspect: QuestionAspect,
) -> list[tuple[str, float]]:
    """Extract factual sentences from a passage that directly support an aspect.

    Enforces focal entity filtering: sentences mentioning a competing tier/entity
    without mentioning the requested entity are rejected.
    Returns list of (claim_sentence, sentence_confidence) pairs.
    """
    text = passage.passage.text
    sentences = [s.strip() for s in SENTENCE_SPLIT_PATTERN.split(text) if len(s.strip()) >= 15]

    aspect_tokens = set(tokenize_text(aspect.aspect, remove_stopwords=True))
    aspect_kw_set = set(aspect.keywords)

    # Detect if aspect has a specific tier/entity modifier (e.g. "business", "pro", "basic")
    aspect_tiers = aspect_tokens & COMMON_TIER_MODIFIERS
    # Detect focal keywords that are not generic category words
    aspect_focal_kw = aspect_kw_set - GENERIC_CATEGORY_WORDS

    extracted: list[tuple[str, float]] = []

    for sentence in sentences:
        # Don't extract question sentences or pure navigation noise
        if sentence.endswith("?") or sentence.lower().startswith("click here"):
            continue

        sent_tokens = set(tokenize_text(sentence, remove_stopwords=True))
        overlap = sent_tokens & aspect_kw_set

        if not overlap:
            continue

        # Focal entity discrimination:
        # If the aspect specifically targets one tier (e.g. "business"),
        # reject sentences that explicitly mention a competing tier (e.g. "basic", "enterprise")
        # unless the sentence ALSO mentions the target tier.
        if aspect_tiers:
            sent_tiers = sent_tokens & COMMON_TIER_MODIFIERS
            competing_tiers = sent_tiers - aspect_tiers
            if competing_tiers and not (sent_tiers & aspect_tiers):
                # Sentence is about a competing tier, not the requested tier
                continue

        # If the aspect had specific non-generic focal keywords (e.g. "business", "limits", "sso"),
        # require the sentence or its section heading to match at least one focal keyword
        # or have at least 2 matching keywords to prevent matching on generic words like "tier" alone.
        heading_tokens = set(tokenize_text(passage.passage.section_heading or "", remove_stopwords=True))
        heading_focal_overlap = heading_tokens & aspect_focal_kw

        if aspect_focal_kw and not (sent_tokens & aspect_focal_kw) and not heading_focal_overlap:
            if len(overlap) < 2:
                continue

        # If the aspect specifically inquires about cost/pricing, require sentence to contain
        # a cost/rate/currency indicator or numeric fee
        if aspect_tokens & INTENT_COST_WORDS:
            has_cost_indicator = bool(
                re.search(r"(\$|\b\d+\b|\bfree\b|\bmonth|\byear|\bannual|\bcost|\bprice|\brate|\bfee)", sentence, re.IGNORECASE)
            )
            if not has_cost_indicator:
                continue

        # Keyword coverage
        coverage = len(overlap) / max(1, len(aspect_kw_set))
        # Normalized BM25 contribution
        bm25_norm = min(1.0, passage.score_breakdown.total_score / 3.0)

        # Transparent heuristic confidence
        confidence = round(0.4 * bm25_norm + 0.6 * coverage, 3)
        confidence = min(1.0, max(0.1, confidence))

        extracted.append((sentence, confidence))

    return extracted


def extract_aspect_claims(
    aspect: QuestionAspect,
    passages: list[ScoredPassage],
) -> list[ClaimEvidence]:
    """Extract traceable claims supporting a specific question aspect."""
    claims: list[ClaimEvidence] = []
    seen_claims: set[str] = set()

    for p in passages:
        candidate_sentences = extract_claims_from_passage(p, aspect)
        for sentence, conf in candidate_sentences:
            norm_key = " ".join(tokenize_text(sentence, remove_stopwords=True))
            if norm_key in seen_claims:
                # Corroborating evidence: find existing claim and attach this passage as second source
                for c in claims:
                    if " ".join(tokenize_text(c.claim, remove_stopwords=True)) == norm_key:
                        if not any(sp.passage.id == p.passage.id for sp in c.supporting_passages):
                            c.supporting_passages.append(p)
                            c.sources.append(
                                SourceReference(
                                    page_url=p.passage.page_url,
                                    page_title=p.passage.page_title,
                                    passage_id=p.passage.id,
                                    section_heading=p.passage.section_heading,
                                    exact_quote=sentence,
                                )
                            )
                            # Boost confidence when multiple independent pages corroborate
                            c.confidence = min(1.0, round(c.confidence + 0.15, 3))
                continue

            seen_claims.add(norm_key)

            source_ref = SourceReference(
                page_url=p.passage.page_url,
                page_title=p.passage.page_title,
                passage_id=p.passage.id,
                section_heading=p.passage.section_heading,
                exact_quote=sentence,
            )

            claims.append(
                ClaimEvidence(
                    claim=sentence,
                    supporting_passages=[p],
                    sources=[source_ref],
                    confidence=conf,
                    aspect=aspect.aspect,
                )
            )

    return claims


# ── 4. Conflict & Missing Information Detection ──────────────────────

NEGATION_WORDS = {"not", "no", "never", "cannot", "neither", "none", "without"}


def detect_conflicts(claims: list[ClaimEvidence]) -> list[ConflictReport]:
    """Detect potential contradictions or conflicts between claims across different sources."""
    conflicts: list[ConflictReport] = []

    # Check for direct numerical or negation conflict within each aspect
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            c1 = claims[i]
            c2 = claims[j]

            # Only check claims under same aspect or sharing common entities
            if c1.aspect != c2.aspect:
                continue

            # Compare from different sources
            urls1 = {s.page_url for s in c1.sources}
            urls2 = {s.page_url for s in c2.sources}
            if urls1 == urls2:
                continue

            t1 = set(tokenize_text(c1.claim, remove_stopwords=False))
            t2 = set(tokenize_text(c2.claim, remove_stopwords=False))

            # Negation polarity conflict
            has_neg1 = bool(t1 & NEGATION_WORDS)
            has_neg2 = bool(t2 & NEGATION_WORDS)

            common_keywords = (t1 & t2) - NEGATION_WORDS
            if len(common_keywords) >= 3 and (has_neg1 != has_neg2):
                c1.conflict_detected = True
                c2.conflict_detected = True
                c1.conflict_details = f"Contradicted by {list(urls2)[0]}"
                c2.conflict_details = f"Contradicted by {list(urls1)[0]}"

                conflicts.append(
                    ConflictReport(
                        aspect=c1.aspect or "General",
                        conflicting_statements=[c1.claim, c2.claim],
                        sources=list(urls1 | urls2),
                        explanation=(
                            f"Sources state contradictory positions regarding: "
                            f"'{' '.join(list(common_keywords)[:3])}'"
                        ),
                    )
                )

            # Numeric values conflict (e.g. differing dollar amounts or counts for same subject)
            nums1 = set(re.findall(r"\$?\b\d+(?:\.\d+)?%?", c1.claim))
            nums2 = set(re.findall(r"\$?\b\d+(?:\.\d+)?%?", c2.claim))
            if nums1 and nums2 and nums1 != nums2 and len(common_keywords) >= 3:
                c1.conflict_detected = True
                c2.conflict_detected = True
                conflicts.append(
                    ConflictReport(
                        aspect=c1.aspect or "General",
                        conflicting_statements=[c1.claim, c2.claim],
                        sources=list(urls1 | urls2),
                        explanation=f"Conflicting numeric figures found: {nums1} vs {nums2}",
                    )
                )

    return conflicts


# ── 5. Deterministic Answer Assembly ────────────────────────────────

def synthesize_deterministic_answer(
    question: str,
    aspects: list[QuestionAspect],
    claims: list[ClaimEvidence],
    missing_aspects: list[str],
    conflicts: list[ConflictReport],
) -> str:
    """Deterministically assemble an answer synthesized from verified claims."""
    if not claims and missing_aspects:
        return (
            f"The crawled website does not contain adequate information to answer the question: '{question}'.\n"
            f"Unanswered aspects: {', '.join(missing_aspects)}."
        )

    sections: list[str] = []

    # Group claims by aspect
    aspect_map: dict[str, list[ClaimEvidence]] = {}
    for c in claims:
        asp = c.aspect or "General"
        aspect_map.setdefault(asp, []).append(c)

    for aspect in aspects:
        asp_name = aspect.aspect
        asp_claims = aspect_map.get(asp_name, [])

        if not asp_claims:
            continue

        section_lines = [f"### {asp_name}"]
        for c in asp_claims:
            # Inline clickable source link
            source_urls = list({s.page_url for s in c.sources})
            sources_formatted = ", ".join(source_urls)
            conf_percent = int(c.confidence * 100)

            conflict_note = f" ⚠️ [Conflict Detected]" if c.conflict_detected else ""
            section_lines.append(
                f"- {c.claim} (Confidence: {conf_percent}%){conflict_note}\n  Source: {sources_formatted}"
            )
        sections.append("\n".join(section_lines))

    # Add conflicts section if any
    if conflicts:
        conflict_lines = ["### Discrepancies and Source Conflicts"]
        for cr in conflicts:
            conflict_lines.append(f"**Aspect:** {cr.aspect}")
            conflict_lines.append(f"- Explanation: {cr.explanation}")
            for stmt in cr.conflicting_statements:
                conflict_lines.append(f"  • \"{stmt}\"")
        sections.append("\n".join(conflict_lines))

    # Add missing aspects section if any
    if missing_aspects:
        missing_lines = ["### Unanswered Aspects"]
        for ma in missing_aspects:
            missing_lines.append(
                f"- No conclusive evidence found on the crawled pages for: **{ma}**"
            )
        sections.append("\n".join(missing_lines))

    return "\n\n".join(sections)


# ── 6. Master Deterministic Extractor ────────────────────────────────

class EvidenceExtractor:
    """Orchestrates deterministic question decomposition, evidence retrieval,

    claim extraction, and answer synthesis.
    """

    def __init__(self, db_path: Path | str = config.DB_PATH) -> None:
        self.db_path = db_path

    def process_question(
        self,
        session_id: str,
        question: str,
    ) -> SearchResult:
        """Run complete deterministic extraction pipeline for a session."""
        # 1. Question Decomposition
        aspects = decompose_question(question)

        # 2. Aspect Evidence Retrieval
        aspect_evidence, all_evidence = retrieve_aspect_evidence(
            session_id=session_id,
            aspects=aspects,
            db_path=self.db_path,
            top_k_per_aspect=config.TOP_K_EVIDENCE,
        )

        # 3. Claim Extraction per aspect
        all_claims: list[ClaimEvidence] = []
        missing_aspects: list[str] = []

        for aspect in aspects:
            passages = aspect_evidence.get(aspect.aspect, [])
            if not passages:
                missing_aspects.append(aspect.aspect)
                continue

            aspect_claims = extract_aspect_claims(aspect, passages)
            if not aspect_claims:
                missing_aspects.append(aspect.aspect)
            else:
                all_claims.extend(aspect_claims)

        # 4. Conflict Detection
        conflicts = detect_conflicts(all_claims)

        # 5. Deterministic Answer Assembly
        answer = synthesize_deterministic_answer(
            question=question,
            aspects=aspects,
            claims=all_claims,
            missing_aspects=missing_aspects,
            conflicts=conflicts,
        )

        # Separate primary evidence vs alternative sources
        primary_evidence = all_evidence[: config.TOP_K_EVIDENCE]
        alternative_sources = all_evidence[config.TOP_K_EVIDENCE : config.TOP_K_EVIDENCE + config.TOP_K_ALTERNATIVES]

        return SearchResult(
            answer=answer,
            claims=all_claims,
            evidence=primary_evidence,
            alternative_sources=alternative_sources,
            question_aspects=aspects,
            missing_aspects=missing_aspects,
            conflicts=conflicts,
            pages_crawled=len({p.passage.page_url for p in all_evidence}),
            pages_failed=0,
            ai_polished=False,
        )
