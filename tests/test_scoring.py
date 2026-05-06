"""Tests for Phase 6 scoring explanation and batch classification.

No network, no DB required.
"""
from unittest.mock import MagicMock

import pytest

from app.services.metadata_sources import (
    classify_enrichment_result,
    choose_best_metadata_explained,
    score_metadata_result_explained,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(**kwargs):
    item = MagicMock()
    item.isbn = kwargs.get("isbn", "")
    item.title = kwargs.get("title", "")
    item.author = kwargs.get("author", "")
    item.language = kwargs.get("language", "")
    return item


def _candidate(**kwargs):
    base = {
        "source": "Google Books API",
        "title": "", "author": "", "description": "",
        "isbn": "", "publisher": "", "language": "",
        "series": "", "series_index": "", "cover_url": "",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# score_metadata_result_explained
# ---------------------------------------------------------------------------

class TestScoreMetadataResultExplained:
    def test_returns_required_keys(self):
        result = score_metadata_result_explained(_item(title="T"), _candidate(title="T"))
        assert {"score", "signals", "warnings"} == set(result.keys())

    def test_signals_keys_present(self):
        result = score_metadata_result_explained(_item(title="T"), _candidate(title="T"))
        signals = result["signals"]
        assert {"isbn_exact_match", "title_similarity", "author_similarity",
                "has_description", "has_cover"} == set(signals.keys())

    def test_isbn_exact_match_adds_80(self):
        item = _item(isbn="9781234567890")
        candidate = _candidate(isbn="9781234567890", title="Book", author="Author")
        result = score_metadata_result_explained(item, candidate)
        assert result["signals"]["isbn_exact_match"] is True
        assert result["score"] >= 80

    def test_no_isbn_match_when_different(self):
        item = _item(isbn="9781234567890")
        candidate = _candidate(isbn="9780000000000")
        result = score_metadata_result_explained(item, candidate)
        assert result["signals"]["isbn_exact_match"] is False

    def test_title_similarity_in_signals(self):
        item = _item(title="The Great Gatsby")
        candidate = _candidate(title="The Great Gatsby")
        result = score_metadata_result_explained(item, candidate)
        assert result["signals"]["title_similarity"] == 1.0

    def test_has_description_true_when_present(self):
        item = _item()
        candidate = _candidate(description="A very interesting book.")
        result = score_metadata_result_explained(item, candidate)
        assert result["signals"]["has_description"] is True

    def test_has_cover_true_when_url_present(self):
        item = _item()
        candidate = _candidate(cover_url="https://example.com/cover.jpg")
        result = score_metadata_result_explained(item, candidate)
        assert result["signals"]["has_cover"] is True

    def test_language_warning_when_differs(self):
        item = _item(language="sv")
        candidate = _candidate(language="en")
        result = score_metadata_result_explained(item, candidate)
        assert any("pråk" in w for w in result["warnings"])

    def test_no_language_warning_when_same(self):
        item = _item(language="en")
        candidate = _candidate(language="en")
        result = score_metadata_result_explained(item, candidate)
        assert not any("pråk" in w for w in result["warnings"])

    def test_no_language_warning_when_item_has_no_language(self):
        item = _item(language="")
        candidate = _candidate(language="fr")
        result = score_metadata_result_explained(item, candidate)
        assert not any("pråk" in w for w in result["warnings"])

    def test_isbn_mismatch_title_warning_when_isbn_matches_but_title_diverges(self):
        item = _item(isbn="9781234567890", title="Book One")
        candidate = _candidate(isbn="9781234567890", title="Completely Different Title Here")
        result = score_metadata_result_explained(item, candidate)
        assert any("ISBN" in w and "titel" in w.lower() for w in result["warnings"])

    def test_missing_author_warning(self):
        item = _item(title="Book")
        candidate = _candidate(author="")
        result = score_metadata_result_explained(item, candidate)
        assert any("rfattare" in w for w in result["warnings"])

    def test_missing_isbn_warning(self):
        item = _item(title="Book")
        candidate = _candidate(isbn="")
        result = score_metadata_result_explained(item, candidate)
        assert any("ISBN" in w for w in result["warnings"])

    def test_score_increases_with_more_fields(self):
        item = _item(title="Book", author="Author")
        minimal = _candidate(title="Book", author="Author")
        rich = _candidate(title="Book", author="Author",
                          description="Desc", cover_url="https://x.com/c.jpg")
        r_minimal = score_metadata_result_explained(item, minimal)
        r_rich = score_metadata_result_explained(item, rich)
        assert r_rich["score"] > r_minimal["score"]

    def test_score_matches_legacy_score_metadata_result(self):
        from app.services.metadata_sources import score_metadata_result
        item = _item(isbn="9781234567890", title="Book", author="Author", language="en")
        candidate = _candidate(isbn="9781234567890", title="Book", author="Author",
                                description="Desc", cover_url="https://x.com/c.jpg")
        legacy = score_metadata_result(item, candidate)
        explained = score_metadata_result_explained(item, candidate)
        assert explained["score"] == legacy


# ---------------------------------------------------------------------------
# classify_enrichment_result
# ---------------------------------------------------------------------------

class TestClassifyEnrichmentResult:
    def test_no_match_below_40(self):
        assert classify_enrichment_result(39.9, {}) == "no_match"
        assert classify_enrichment_result(0, {}) == "no_match"

    def test_manual_only_40_to_69(self):
        assert classify_enrichment_result(40.0, {}) == "manual_only"
        assert classify_enrichment_result(69.9, {}) == "manual_only"

    def test_review_needed_70_to_89(self):
        assert classify_enrichment_result(70.0, {}) == "review_needed"
        assert classify_enrichment_result(89.9, {}) == "review_needed"

    def test_review_needed_above_90_without_isbn(self):
        assert classify_enrichment_result(95.0, {"isbn_exact_match": False}) == "review_needed"
        assert classify_enrichment_result(95.0, {}) == "review_needed"

    def test_auto_apply_at_90_plus_with_isbn(self):
        assert classify_enrichment_result(90.0, {"isbn_exact_match": True}) == "auto_apply"
        assert classify_enrichment_result(155.0, {"isbn_exact_match": True}) == "auto_apply"

    def test_boundary_exactly_90_with_isbn(self):
        assert classify_enrichment_result(90.0, {"isbn_exact_match": True}) == "auto_apply"

    def test_boundary_exactly_70(self):
        assert classify_enrichment_result(70.0, {"isbn_exact_match": False}) == "review_needed"


# ---------------------------------------------------------------------------
# choose_best_metadata_explained
# ---------------------------------------------------------------------------

class TestChooseBestMetadataExplained:
    def test_empty_results_returns_no_match(self):
        result = choose_best_metadata_explained(_item(), [])
        assert result["best"] is None
        assert result["classification"] == "no_match"
        assert result["all_scored"] == []

    def test_returns_required_keys(self):
        item = _item(title="Book", author="Author")
        candidate = _candidate(title="Book", author="Author",
                                description="Desc", cover_url="https://x.com/c.jpg")
        result = choose_best_metadata_explained(item, [candidate])
        assert {"best", "score", "signals", "warnings",
                "classification", "all_scored"} == set(result.keys())

    def test_best_is_highest_scoring_candidate(self):
        item = _item(isbn="9781234567890", title="Book", author="Author")
        weak = _candidate(title="Something Else")
        strong = _candidate(isbn="9781234567890", title="Book", author="Author",
                             description="Desc")
        result = choose_best_metadata_explained(item, [weak, strong])
        assert result["best"] is strong

    def test_all_scored_contains_every_candidate(self):
        item = _item(title="Book")
        candidates = [_candidate(title=f"Book {i}") for i in range(4)]
        result = choose_best_metadata_explained(item, candidates)
        assert len(result["all_scored"]) == 4

    def test_all_scored_sorted_descending(self):
        item = _item(isbn="9781234567890", title="Book", author="Author")
        candidates = [
            _candidate(title="Something Else"),
            _candidate(isbn="9781234567890", title="Book", author="Author", description="D"),
            _candidate(title="Book", author="Author"),
        ]
        result = choose_best_metadata_explained(item, candidates)
        scores = [s["score"] for s in result["all_scored"]]
        assert scores == sorted(scores, reverse=True)

    def test_no_match_when_best_below_minimum(self):
        item = _item(title="Unique Obscure Title XYZ")
        candidate = _candidate(title="Totally Different")
        result = choose_best_metadata_explained(item, [candidate], minimum_score=40)
        assert result["best"] is None
        assert result["classification"] == "no_match"

    def test_classification_auto_apply_for_isbn_high_score(self):
        item = _item(isbn="9781234567890", title="Book", author="Author")
        candidate = _candidate(isbn="9781234567890", title="Book", author="Author",
                                description="Desc", cover_url="https://x.com/c.jpg")
        result = choose_best_metadata_explained(item, [candidate])
        assert result["classification"] == "auto_apply"
        assert result["signals"]["isbn_exact_match"] is True

    def test_classification_review_needed_for_title_author_only(self):
        item = _item(title="The Great Book", author="Famous Author")
        candidate = _candidate(title="The Great Book", author="Famous Author",
                                description="Desc", cover_url="https://x.com/c.jpg")
        result = choose_best_metadata_explained(item, [candidate])
        # No ISBN match → max score = 45 + 25 + 5 + 5 = 80 → review_needed
        assert result["classification"] == "review_needed"
        assert result["signals"]["isbn_exact_match"] is False

    def test_all_scored_entries_have_classification(self):
        item = _item(title="Book")
        candidates = [_candidate(title="Book"), _candidate(title="Other")]
        result = choose_best_metadata_explained(item, candidates)
        for entry in result["all_scored"]:
            assert "classification" in entry
            assert entry["classification"] in {
                "auto_apply", "review_needed", "manual_only", "no_match"
            }
