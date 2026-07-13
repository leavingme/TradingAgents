"""Structured, auditable evidence models for news and macro observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import math
import re
from urllib.parse import urlsplit


@dataclass(frozen=True)
class NewsItem:
    source_id: str
    title: str
    publisher: str
    published_at: str
    url: str
    summary: str
    symbols: tuple[str, ...]
    vendor: str


@dataclass(frozen=True)
class NewsFeed:
    items: tuple[NewsItem, ...]
    scope: str
    requested_start: str
    requested_end: str
    query: str = ""


@dataclass(frozen=True)
class MacroObservation:
    source_id: str
    series_id: str
    title: str
    units: str
    frequency: str
    observed_at: str
    value: float
    vendor: str


@dataclass(frozen=True)
class MacroSeries:
    series_id: str
    title: str
    units: str
    frequency: str
    requested_start: str
    requested_end: str
    observations: tuple[MacroObservation, ...]


def parse_external_datetime(value: object) -> str:
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("published_at is missing")
        if raw.isdigit():
            dt = datetime.fromtimestamp(float(raw), tz=timezone.utc)
        else:
            candidate = raw.replace("Z", "+00:00")
            for parser in (
                lambda: datetime.fromisoformat(candidate),
                lambda: datetime.strptime(raw, "%Y%m%dT%H%M%S"),
                lambda: datetime.strptime(raw, "%Y-%m-%d %H:%M:%S"),
                lambda: datetime.strptime(raw, "%Y-%m-%d"),
            ):
                try:
                    dt = parser()
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"invalid external datetime: {raw!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def news_source_id(*, vendor: str, title: str, published_at: str, url: str) -> str:
    material = "\x1f".join((vendor, title.strip(), published_at, url.strip()))
    return "news_" + hashlib.sha256(material.encode()).hexdigest()[:20]


def macro_source_id(series_id: str, observed_at: str) -> str:
    return "macro_" + hashlib.sha256(
        f"fred\x1f{series_id}\x1f{observed_at}".encode()
    ).hexdigest()[:20]


def validate_news_feed(feed: NewsFeed, *, symbol: str | None = None) -> NewsFeed:
    if not isinstance(feed, NewsFeed):
        raise TypeError("news vendor must return NewsFeed")
    start = datetime.fromisoformat(feed.requested_start).date()
    end = datetime.fromisoformat(feed.requested_end).date()
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    accepted: list[NewsItem] = []
    for item in feed.items:
        try:
            published = datetime.fromisoformat(parse_external_datetime(item.published_at))
        except ValueError:
            continue
        if not start <= published.date() <= end:
            continue
        if not item.title.strip() or not item.publisher.strip():
            continue
        parsed_url = urlsplit(item.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        symbols = tuple(value.upper() for value in item.symbols)
        if symbol and symbol.upper() not in symbols:
            continue
        url_identity = item.url.strip().lower()
        title_identity = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", item.title.lower())
        if url_identity in seen_urls or title_identity in seen_titles:
            continue
        seen_urls.add(url_identity)
        seen_titles.add(title_identity)
        canonical_time = published.isoformat()
        accepted.append(replace(
            item,
            published_at=canonical_time,
            symbols=symbols,
            source_id=news_source_id(
                vendor=item.vendor, title=item.title,
                published_at=canonical_time, url=item.url,
            ),
        ))
    if not accepted:
        raise ValueError("no news items passed source/date/URL/symbol validation")
    accepted.sort(key=lambda item: item.published_at, reverse=True)
    return replace(feed, items=tuple(accepted))


def validate_macro_series(series: MacroSeries) -> MacroSeries:
    if not isinstance(series, MacroSeries):
        raise TypeError("macro vendor must return MacroSeries")
    if not all((series.series_id.strip(), series.title.strip(), series.units.strip(), series.frequency.strip())):
        raise ValueError("macro series is missing ID/title/units/frequency metadata")
    start = datetime.fromisoformat(series.requested_start).date()
    cutoff = datetime.fromisoformat(series.requested_end).date()
    seen: set[str] = set()
    accepted = []
    for observation in series.observations:
        observed = datetime.fromisoformat(observation.observed_at).date()
        if (
            not start <= observed <= cutoff
            or observation.series_id != series.series_id
            or observation.units != series.units
            or observation.frequency != series.frequency
            or not math.isfinite(float(observation.value))
            or observation.source_id != macro_source_id(series.series_id, observation.observed_at)
        ):
            continue
        if observation.source_id in seen:
            continue
        seen.add(observation.source_id)
        accepted.append(observation)
    if not accepted:
        raise ValueError("no macro observations passed cutoff and series validation")
    accepted.sort(key=lambda observation: observation.observed_at)
    return replace(series, observations=tuple(accepted))


def render_news_feed(feed: NewsFeed) -> str:
    lines = [f"## Validated news evidence ({feed.requested_start} to {feed.requested_end})"]
    for item in feed.items:
        lines.extend([
            "", f"### [{item.source_id}] {item.title}",
            f"- Publisher: {item.publisher}",
            f"- Published: {item.published_at}",
            f"- URL: {item.url}",
            f"- Symbols: {', '.join(item.symbols) or 'GLOBAL'}",
        ])
        if item.summary:
            lines.append(f"- Summary: {item.summary}")
    return "\n".join(lines)


def render_macro_series(series: MacroSeries) -> str:
    lines = [
        f"## Validated macro evidence: {series.title} ({series.series_id})",
        f"- Units: {series.units}", f"- Frequency: {series.frequency}",
        "", "| source_id | Date | Value |", "|---|---|---:|",
    ]
    for item in series.observations[-40:]:
        lines.append(f"| {item.source_id} | {item.observed_at} | {item.value} |")
    return "\n".join(lines)


_SOURCE_ID = re.compile(r"\b(?:news|macro)_[0-9a-f]{8,64}\b")
_MATERIAL_CLAIM = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?%|\$\d|"
    r"announc(?:e|ed|es)|report(?:ed|s)?|rais(?:e|ed|es)|cut|launch(?:ed|es)?)\b",
    re.IGNORECASE,
)


def validate_report_citations(report: str, evidence_texts: list[str]) -> str:
    """Reject unknown citations and uncited paragraphs containing material claims."""
    available = set()
    for text in evidence_texts:
        available.update(_SOURCE_ID.findall(str(text)))
    if not available:
        raise ValueError("news report has no validated source records")
    cited = set(_SOURCE_ID.findall(report))
    unknown = cited - available
    if unknown:
        raise ValueError("news report cites unknown source_id: " + ", ".join(sorted(unknown)))
    if not cited:
        raise ValueError("news report must cite validated source_id values")
    for paragraph in re.split(r"\n\s*\n", report):
        text = paragraph.strip()
        if not text or text.startswith("|") or text.startswith("#"):
            continue
        if _MATERIAL_CLAIM.search(text) and not (_SOURCE_ID.findall(text)):
            raise ValueError("decision-material news claim is missing a source_id citation")
    return report
