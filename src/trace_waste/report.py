"""Analysis and reporting: turn findings into waste totals.

The accounting rule that keeps the numbers honest: each event's tokens
can be counted as waste at most once. Findings are applied in a fixed
order (category order, then event index) and each finding only claims
tokens no earlier finding has claimed, so overlapping detections never
inflate the total.
"""

from __future__ import annotations

from dataclasses import dataclass

from .judge import CATEGORIES, Finding, Judge
from .traceio import Event


@dataclass
class CategoryTotal:
    category: str
    findings: int = 0
    waste_tokens: int = 0


@dataclass
class Report:
    events: int
    total_tokens: int
    waste_tokens: int
    categories: dict
    findings: list

    @property
    def waste_percent(self) -> float:
        if self.total_tokens <= 0:
            return 0.0
        return 100.0 * self.waste_tokens / self.total_tokens

    def savings_usd(self, price_per_1m: float | None) -> float | None:
        """Dollar value of the waste tokens at a per-1M-token price."""
        if price_per_1m is None:
            return None
        return self.waste_tokens * price_per_1m / 1_000_000


def _category_rank(category: str) -> int:
    try:
        return CATEGORIES.index(category)
    except ValueError:
        return len(CATEGORIES)


def analyze(events: list[Event], judge: Judge) -> Report:
    """Run a judge over the events and total up the waste."""
    findings = sorted(
        judge.judge(events),
        key=lambda f: (_category_rank(f.category), f.index),
    )
    claimed: dict = {}
    categories: dict = {}
    for finding in findings:
        spans = finding.spans or _default_span(events, finding)
        effective = 0
        for span in spans:
            if not 0 <= span.index < len(events):
                continue
            already = claimed.get(span.index, 0)
            available = max(0, events[span.index].tokens - already)
            take = min(span.tokens, available)
            claimed[span.index] = already + take
            effective += take
        finding.tokens = effective
        total = categories.setdefault(
            finding.category, CategoryTotal(category=finding.category)
        )
        total.findings += 1
        total.waste_tokens += effective
    return Report(
        events=len(events),
        total_tokens=sum(e.tokens for e in events),
        waste_tokens=sum(f.tokens for f in findings),
        categories=categories,
        findings=findings,
    )


def _default_span(events: list[Event], finding: Finding):
    from .judge import Span

    if 0 <= finding.index < len(events):
        return (Span(finding.index, events[finding.index].tokens),)
    return ()


def render_json(report: Report, price_per_1m: float | None = None) -> dict:
    """Machine-readable report."""
    return {
        "events": report.events,
        "total_tokens": report.total_tokens,
        "waste_tokens": report.waste_tokens,
        "waste_percent": round(report.waste_percent, 2),
        "categories": {
            name: {"findings": t.findings, "waste_tokens": t.waste_tokens}
            for name, t in sorted(report.categories.items())
        },
        "findings": [
            {
                "index": f.index,
                "category": f.category,
                "tokens": f.tokens,
                "reason": f.reason,
            }
            for f in sorted(report.findings, key=lambda f: f.index)
        ],
        "savings": {
            "tokens": report.waste_tokens,
            "usd": (
                round(report.savings_usd(price_per_1m), 6)
                if price_per_1m is not None
                else None
            ),
        },
    }


def render_text(report: Report, price_per_1m: float | None = None) -> str:
    """Human-readable report."""
    lines = [
        "trace-waste report",
        f"events: {report.events}   total tokens (est.): {report.total_tokens:,}",
        "",
    ]
    if not report.findings:
        lines.append("no waste detected")
        return "\n".join(lines)
    lines.append("waste by category:")
    width = max(len(name) for name in report.categories)
    for total in sorted(
        report.categories.values(), key=lambda t: -t.waste_tokens
    ):
        share = (
            100.0 * total.waste_tokens / report.total_tokens
            if report.total_tokens
            else 0.0
        )
        lines.append(
            f"  {total.category:<{width}}  {total.findings:>3} findings"
            f"  {total.waste_tokens:>8,} tokens  {share:5.1f}%"
        )
    lines.append("")
    lines.append(
        f"total waste: {report.waste_tokens:,} tokens "
        f"({report.waste_percent:.1f}% of the run)"
    )
    savings = f"estimated savings if pruned: {report.waste_tokens:,} tokens"
    usd = report.savings_usd(price_per_1m)
    if usd is not None:
        savings += f" (~${usd:,.4f} at ${price_per_1m:,.2f} / 1M tokens)"
    lines.append(savings)
    lines.append("")
    lines.append("findings:")
    for finding in sorted(report.findings, key=lambda f: f.index):
        lines.append(
            f"  event {finding.index:>3}  [{finding.category}]"
            f"  {finding.tokens:,} tokens  {finding.reason}"
        )
    return "\n".join(lines)
