"""Golden dataset definitions for RAG answer quality evaluation.

Each ``GoldenCase`` pairs a question with the *expected* answer characteristics:
keywords that should appear, source URLs that should be retrieved, minimum
answer length, and concepts the answer should mention.  ``GoldenDataset``
groups cases together and ships a small default set that exercises core
capabilities (pricing, features, support, etc.).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldenCase:
    """A single golden evaluation case.

    Attributes
    ----------
    question:
        The user question text.
    label:
        Short identifier for the case (used in reports).
    expected_keywords:
        Words/phrases the answer *must* contain (case-insensitive).
    expected_sources:
        URL substrings that should appear among the retrieved source URLs.
    min_answer_length:
        Minimum character count for a valid (non-empty) answer.
    expected_concepts:
        Broader topic concepts the answer should address (used for
        semantic coverage scoring).
    """

    question: str
    label: str = ""
    expected_keywords: list[str] = field(default_factory=list)
    expected_sources: list[str] = field(default_factory=list)
    min_answer_length: int = 10
    expected_concepts: list[str] = field(default_factory=list)

    @property
    def short_label(self) -> str:
        return self.label or self.question[:40]


@dataclass
class GoldenDataset:
    """An ordered collection of ``GoldenCase`` objects.

    Provides a ``load_default()`` class method that returns a small
    representative dataset suitable for quick quality sweeps.
    """

    cases: list[GoldenCase] = field(default_factory=list)

    @classmethod
    def load_default(cls) -> GoldenDataset:
        """Return a small default golden dataset with 6 representative cases."""
        return cls(
            cases=[
                GoldenCase(
                    question="What pricing plans do you offer?",
                    label="pricing_plans",
                    expected_keywords=["plan", "price"],
                    expected_sources=["/pricing"],
                    min_answer_length=20,
                    expected_concepts=["pricing", "plans"],
                ),
                GoldenCase(
                    question="How does the free trial work?",
                    label="free_trial",
                    expected_keywords=["trial", "free"],
                    expected_sources=["/trial", "/pricing"],
                    min_answer_length=15,
                    expected_concepts=["trial", "getting started"],
                ),
                GoldenCase(
                    question="What integrations do you support?",
                    label="integrations",
                    expected_keywords=["integration", "support"],
                    expected_sources=["/integrations"],
                    min_answer_length=15,
                    expected_concepts=["integrations", "connect"],
                ),
                GoldenCase(
                    question="How do I contact support?",
                    label="support_contact",
                    expected_keywords=["support", "contact"],
                    expected_sources=["/support", "/contact"],
                    min_answer_length=10,
                    expected_concepts=["support", "help"],
                ),
                GoldenCase(
                    question="What security certifications do you have?",
                    label="security_certs",
                    expected_keywords=["security", "certification"],
                    expected_sources=["/security"],
                    min_answer_length=15,
                    expected_concepts=["security", "compliance"],
                ),
                GoldenCase(
                    question="Is there a team plan available?",
                    label="team_plan",
                    expected_keywords=["team", "plan"],
                    expected_sources=["/pricing", "/teams"],
                    min_answer_length=10,
                    expected_concepts=["team", "enterprise"],
                ),
            ],
        )

    def __len__(self) -> int:
        return len(self.cases)

    def __iter__(self) -> Iterator[GoldenCase]:
        return iter(self.cases)
