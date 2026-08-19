"""Representative benchmark queries.

Each ``BenchmarkQuery`` carries the question text plus optional expected-answer
fragments so the runner can verify correctness alongside latency.  The query
set is intentionally small (5-10 representative questions) so a benchmark run
completes quickly while still exercising the full RAG pipeline.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkQuery:
    """A single benchmark question with optional quality hints."""

    text: str
    label: str = ""
    expected_fragment: str = ""

    @property
    def short_label(self) -> str:
        return self.label or self.text[:40]


QUERIES: list[BenchmarkQuery] = [
    BenchmarkQuery(
        text="What pricing plans do you offer?",
        label="pricing_plans",
        expected_fragment="$",
    ),
    BenchmarkQuery(
        text="How does the free trial work?",
        label="free_trial",
        expected_fragment="trial",
    ),
    BenchmarkQuery(
        text="What are the API rate limits?",
        label="api_rate_limits",
    ),
    BenchmarkQuery(
        text="How do I upgrade my account?",
        label="upgrade_account",
    ),
    BenchmarkQuery(
        text="Is there a team plan available?",
        label="team_plan",
    ),
    BenchmarkQuery(
        text="What integrations do you support?",
        label="integrations",
    ),
    BenchmarkQuery(
        text="How do I contact support?",
        label="support_contact",
    ),
    BenchmarkQuery(
        text="What security certifications do you have?",
        label="security_certs",
    ),
]
