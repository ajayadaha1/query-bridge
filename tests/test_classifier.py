"""Tests for classifier."""

from querybridge.classifier.question_classifier import QuestionClassifier


class TestQuestionClassifier:
    def setup_method(self):
        self.classifier = QuestionClassifier()

    def test_count_question(self):
        profile = self.classifier.classify("How many users are there?")
        assert profile.question_type == "count"

    def test_trend_question(self):
        profile = self.classifier.classify("Show me the monthly trend of signups")
        assert profile.question_type == "trend"

    def test_comparison_question(self):
        profile = self.classifier.classify("Compare revenue between Q1 and Q2")
        assert profile.question_type == "comparison"

    def test_returns_profile_with_budgets(self):
        profile = self.classifier.classify("Show all records")
        assert hasattr(profile, "phase_budgets")
        assert "explore" in profile.phase_budgets
        assert "execute" in profile.phase_budgets

    def test_empty_question(self):
        profile = self.classifier.classify("")
        assert profile.question_type is not None
