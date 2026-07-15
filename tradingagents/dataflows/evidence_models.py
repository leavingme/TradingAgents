"""Structured, auditable evidence models for news, macro, and predictions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


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
    published_at: str = ""
    vintage_date: str = ""
    revision_status: str = ""


@dataclass(frozen=True)
class MacroSeries:
    series_id: str
    title: str
    units: str
    frequency: str
    requested_start: str
    requested_end: str
    observations: tuple[MacroObservation, ...]
    vendor: str = ""
    vintage_date: str = ""
    revision_policy: str = ""
    requested_indicator: str = ""


@dataclass(frozen=True)
class PredictionOutcome:
    label: str
    probability: float


@dataclass(frozen=True)
class PredictionMarket:
    source_id: str
    event_id: str
    event_title: str
    market_id: str
    condition_id: str
    question: str
    slug: str
    url: str
    expires_at: str
    observed_at: str
    outcomes: tuple[PredictionOutcome, ...]
    volume: float
    one_week_probability_change: float | None
    vendor: str
    vendor_call_id: str = ""
    active: bool = True
    closed: bool = False
    archived: bool = False


@dataclass(frozen=True)
class PredictionMarketFeed:
    topic: str
    observed_at: str
    requested_limit: int
    markets: tuple[PredictionMarket, ...]


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


def macro_source_id(
    series_id: str,
    observed_at: str,
    *,
    vendor: str = "fred",
    vintage_date: str = "",
) -> str:
    return "macro_" + hashlib.sha256(
        f"{vendor}\x1f{series_id}\x1f{observed_at}\x1f{vintage_date}".encode()
    ).hexdigest()[:20]


def prediction_source_id(*, vendor: str, event_id: str, market_id: str) -> str:
    material = "\x1f".join((vendor.strip(), event_id.strip(), market_id.strip()))
    return "prediction_" + hashlib.sha256(material.encode()).hexdigest()[:20]


def _canonical_news_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    query = urlencode(sorted(
        (key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"fbclid", "gclid"}
    ))
    return urlunsplit((
        parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path,
        query, "",
    ))


def validate_news_feed(
    feed: NewsFeed,
    *,
    symbol: str | None = None,
    expected_vendor: str | None = None,
    information_cutoff: str | None = None,
    now: datetime | None = None,
) -> NewsFeed:
    if not isinstance(feed, NewsFeed):
        raise TypeError("news vendor must return NewsFeed")
    start = datetime.fromisoformat(feed.requested_start).date()
    end = datetime.fromisoformat(feed.requested_end).date()
    if start > end:
        raise ValueError("news requested_start is after requested_end")
    cutoff = (
        datetime.fromisoformat(information_cutoff.replace("Z", "+00:00"))
        if information_cutoff
        else (now or datetime.now(timezone.utc))
    )
    if cutoff.tzinfo is None:
        raise ValueError("news information_cutoff must include a timezone")
    cutoff = cutoff.astimezone(timezone.utc)
    if end > cutoff.date():
        raise ValueError("news requested_end exceeds information cutoff")
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    accepted: list[NewsItem] = []
    for item in feed.items:
        try:
            published = datetime.fromisoformat(parse_external_datetime(item.published_at))
        except ValueError:
            continue
        if not start <= published.date() <= end or published > cutoff:
            continue
        if (
            not item.title.strip()
            or not item.publisher.strip()
            or not item.summary.strip()
            or not item.vendor.strip()
            or (expected_vendor and item.vendor != expected_vendor)
        ):
            continue
        parsed_url = urlsplit(item.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        symbols = tuple(value.upper() for value in item.symbols)
        if symbol and symbol.upper() not in symbols:
            continue
        canonical_url = _canonical_news_url(item.url)
        url_identity = canonical_url.casefold()
        title_identity = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "", item.title.lower())
        if url_identity in seen_urls or title_identity in seen_titles:
            continue
        seen_urls.add(url_identity)
        seen_titles.add(title_identity)
        canonical_time = published.isoformat()
        accepted.append(replace(
            item,
            published_at=canonical_time,
            url=canonical_url,
            symbols=symbols,
            source_id=news_source_id(
                vendor=item.vendor, title=item.title,
                published_at=canonical_time, url=canonical_url,
            ),
        ))
    if not accepted:
        raise ValueError("no news items passed source/date/URL/symbol validation")
    accepted.sort(key=lambda item: item.published_at, reverse=True)
    return replace(feed, items=tuple(accepted))


def validate_macro_series(
    series: MacroSeries,
    *,
    expected_vendor: str | None = None,
    expected_indicator: str | None = None,
    information_cutoff: str | None = None,
    now: datetime | None = None,
) -> MacroSeries:
    if not isinstance(series, MacroSeries):
        raise TypeError("macro vendor must return MacroSeries")
    if not all((
        series.series_id.strip(), series.title.strip(), series.units.strip(),
        series.frequency.strip(), series.vendor.strip(), series.vintage_date.strip(),
        series.revision_policy.strip(), series.requested_indicator.strip(),
    )):
        raise ValueError(
            "macro series is missing request/ID/title/units/frequency/vintage metadata"
        )
    if expected_vendor and series.vendor != expected_vendor:
        raise ValueError("macro series vendor does not match routed vendor")
    if (
        expected_indicator
        and series.requested_indicator.casefold() != expected_indicator.casefold()
    ):
        raise ValueError("macro series does not match requested indicator")
    start = datetime.fromisoformat(series.requested_start).date()
    requested_end = datetime.fromisoformat(series.requested_end).date()
    cutoff_time = (
        datetime.fromisoformat(information_cutoff.replace("Z", "+00:00"))
        if information_cutoff
        else (now or datetime.now(timezone.utc))
    )
    if cutoff_time.tzinfo is None:
        raise ValueError("macro information_cutoff must include a timezone")
    cutoff = cutoff_time.astimezone(timezone.utc).date()
    vintage = datetime.fromisoformat(series.vintage_date).date()
    if start > requested_end or requested_end > cutoff or vintage > cutoff:
        raise ValueError("macro request or vintage exceeds information cutoff")
    seen: set[str] = set()
    accepted = []
    for observation in series.observations:
        observed = datetime.fromisoformat(observation.observed_at).date()
        published = datetime.fromisoformat(observation.published_at).date()
        observation_vintage = datetime.fromisoformat(observation.vintage_date).date()
        if (
            not start <= observed <= requested_end
            or not observed <= published <= cutoff
            or not published <= observation_vintage <= cutoff
            or observation.series_id != series.series_id
            or observation.title != series.title
            or observation.units != series.units
            or observation.frequency != series.frequency
            or observation.vendor != series.vendor
            or observation.vintage_date != series.vintage_date
            or observation.revision_status not in {"initial", "revised"}
            or not math.isfinite(float(observation.value))
            or observation.source_id != macro_source_id(
                series.series_id,
                observation.observed_at,
                vendor=series.vendor,
                vintage_date=series.vintage_date,
            )
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


def validate_prediction_market_feed(
    feed: PredictionMarketFeed,
    *,
    expected_vendor: str | None = None,
    expected_topic: str | None = None,
    information_cutoff: str | None = None,
    require_call_id: bool = False,
    now: datetime | None = None,
) -> PredictionMarketFeed:
    """Validate live prediction evidence before it is rendered for an LLM."""
    if not isinstance(feed, PredictionMarketFeed):
        raise TypeError("prediction-market vendor must return PredictionMarketFeed")
    if not feed.topic.strip():
        raise ValueError("prediction-market topic is missing")
    if expected_topic and feed.topic.strip().casefold() != expected_topic.strip().casefold():
        raise ValueError("prediction-market feed topic does not match the request")
    try:
        requested_limit = int(feed.requested_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("prediction-market requested_limit must be an integer") from exc
    if not 1 <= requested_limit <= 20:
        raise ValueError("prediction-market requested_limit must be between 1 and 20")

    observed = datetime.fromisoformat(parse_external_datetime(feed.observed_at))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    if observed > current + timedelta(minutes=5):
        raise ValueError("prediction-market observed_at is in the future")
    if information_cutoff:
        cutoff = datetime.fromisoformat(parse_external_datetime(information_cutoff))
        if observed > cutoff:
            raise ValueError("prediction-market observed_at exceeds information_cutoff")

    seen: set[str] = set()
    accepted: list[PredictionMarket] = []
    for market in feed.markets:
        try:
            market_observed = datetime.fromisoformat(
                parse_external_datetime(market.observed_at)
            )
            expires = datetime.fromisoformat(parse_external_datetime(market.expires_at))
        except (ValueError, OverflowError, OSError):
            continue
        if market_observed != observed or expires <= observed:
            continue
        if not market.active or market.closed or market.archived:
            continue
        if not all((
            market.event_id.strip(), market.event_title.strip(),
            market.market_id.strip(), market.condition_id.strip(),
            market.question.strip(), market.vendor.strip(),
        )):
            continue
        if expected_vendor and market.vendor != expected_vendor:
            continue
        expected_source_id = prediction_source_id(
            vendor=market.vendor,
            event_id=market.event_id,
            market_id=market.market_id,
        )
        if market.source_id != expected_source_id or market.source_id in seen:
            continue
        parsed_url = urlsplit(market.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        if len(market.outcomes) < 2:
            continue
        labels = [outcome.label.strip() for outcome in market.outcomes]
        probabilities = [float(outcome.probability) for outcome in market.outcomes]
        if (
            not all(labels)
            or len(set(labels)) != len(labels)
            or not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in probabilities)
            or not math.isclose(sum(probabilities), 1.0, abs_tol=0.02)
        ):
            continue
        if not math.isfinite(float(market.volume)) or float(market.volume) < 0:
            continue
        weekly_change = market.one_week_probability_change
        if weekly_change is not None and (
            not math.isfinite(float(weekly_change))
            or not -1.0 <= float(weekly_change) <= 1.0
        ):
            continue
        if require_call_id and not market.vendor_call_id.strip():
            continue
        seen.add(market.source_id)
        accepted.append(replace(
            market,
            expires_at=expires.isoformat(),
            observed_at=market_observed.isoformat(),
            outcomes=tuple(
                PredictionOutcome(label=label, probability=probability)
                for label, probability in zip(labels, probabilities)
            ),
            volume=float(market.volume),
            one_week_probability_change=(
                float(weekly_change) if weekly_change is not None else None
            ),
        ))
    if not accepted:
        raise ValueError(
            "no prediction markets passed ID/expiry/probability/source validation"
        )
    accepted.sort(key=lambda market: market.volume, reverse=True)
    return replace(
        feed,
        observed_at=observed.isoformat(),
        requested_limit=requested_limit,
        markets=tuple(accepted[:requested_limit]),
    )


def bind_prediction_market_call_id(
    feed: PredictionMarketFeed, call_id: str
) -> PredictionMarketFeed:
    if not call_id.strip():
        raise ValueError("prediction-market vendor call_id is missing")
    return replace(
        feed,
        markets=tuple(
            replace(market, vendor_call_id=call_id) for market in feed.markets
        ),
    )


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
        f"- Vendor: {series.vendor}", f"- Vintage date: {series.vintage_date}",
        f"- Revision policy: {series.revision_policy}",
        f"- Requested indicator: {series.requested_indicator}",
        "", "| source_id | Observation date | Published | Revision | Value |",
        "|---|---|---|---|---:|",
    ]
    for item in series.observations[-40:]:
        lines.append(
            f"| {item.source_id} | {item.observed_at} | {item.published_at} | "
            f"{item.revision_status} | {item.value} |"
        )
    return "\n".join(lines)


def render_prediction_market_feed(feed: PredictionMarketFeed) -> str:
    lines = [
        f"## Validated prediction-market evidence: {feed.topic}",
        f"- Observed at: {feed.observed_at}",
        "- Probabilities are market prices, not certain forecasts.",
    ]
    for market in feed.markets:
        outcomes = ", ".join(
            f"{outcome.label} {outcome.probability:.1%}"
            for outcome in market.outcomes
        )
        lines.extend([
            "",
            f"### [{market.source_id}] {market.question}",
            f"- Event: {market.event_title} (event_id={market.event_id})",
            f"- Market ID: {market.market_id}",
            f"- Condition ID: {market.condition_id}",
            f"- Outcomes: {outcomes}",
            f"- Volume: ${market.volume:,.0f}",
            f"- Expires: {market.expires_at}",
            f"- Vendor call ID: {market.vendor_call_id}",
            f"- URL: {market.url}",
        ])
        if market.one_week_probability_change is not None:
            lines.append(
                "- One-week probability change: "
                f"{market.one_week_probability_change * 100:+.1f}pp"
            )
    return "\n".join(lines)


_SOURCE_ID = re.compile(r"\b(?:news|macro|prediction)_[0-9a-f]{8,64}\b")
_MATERIAL_CLAIM = re.compile(
    r"(?:\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:\.\d+)?\s*%|\$\s*\d|"
    r"\bannounc(?:e|ed|es)\b|\breport(?:ed|s)?\b|\brais(?:e|ed|es)\b|"
    r"\bcut\b|\blaunch(?:ed|es)?\b)",
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


def remove_uncited_material_claims(report: str) -> str:
    """Drop unsupported material paragraphs after the single model correction.

    This is deliberately narrower than citation validation: unknown citations
    and reports with no valid citations still fail hard. Only paragraphs that
    contain a decision-material claim but no source_id are removed.
    """
    kept: list[str] = []
    for paragraph in re.split(r"\n\s*\n", report):
        text = paragraph.strip()
        if not text:
            continue
        exempt = text.startswith("|") or text.startswith("#")
        if not exempt and _MATERIAL_CLAIM.search(text) and not _SOURCE_ID.findall(text):
            continue
        kept.append(text)
    return "\n\n".join(kept)
