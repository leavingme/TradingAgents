"""Symbol normalization and market-data error types for vendor calls.

Westock (the default vendor) uses specific ticker conventions that
differ from the broker / TradingView / MT5 style symbols users often type:

    user types        Westock wants       why
    ---------------   ---------------   -----------------------------------
    XAUUSD, XAUUSD+   GC=F              gold has no forex pair on Westock;
                                        it is quoted as a COMEX future
    EURUSD            EURUSD=X          spot forex pairs take a ``=X`` suffix
    BTCUSD            BTC-USD           crypto pairs use a ``-`` separator
    SPX500, US500     ^GSPC             index CFDs map to Westock index symbols

Passing the raw broker symbol to Westock returns an empty result, which the
agents previously received as free text and could hallucinate a price
around (see issue #781). Centralizing the mapping here means every westock
entry point resolves symbols the same way, and new instruments are added by
appending a table row rather than editing call sites.
"""

from __future__ import annotations

import logging
import re

# NoMarketDataError lives in the vendor-error taxonomy (errors.py); re-exported
# here for the many call sites that import it alongside normalize_symbol.
from .errors import NoMarketDataError as NoMarketDataError

logger = logging.getLogger(__name__)


# ISO-4217 codes common enough to appear in retail forex pairs. A bare
# six-letter symbol whose halves are BOTH in this set is treated as a spot
# forex pair and given Westock's ``=X`` suffix.
_FOREX_CURRENCIES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
        "CNY", "CNH", "HKD", "SGD", "SEK", "NOK", "DKK", "PLN",
        "MXN", "ZAR", "TRY", "INR", "KRW", "BRL", "RUB", "THB",
    }
)

# Crypto bases that brokers quote against USD without a separator.
_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX", "LINK"}
)

# Explicit aliases for instruments whose broker symbol does not map to a
# Westock symbol by rule. Metals/energy resolve to their front-month future;
# index CFD names resolve to the underlying Westock index symbol. Extend by
# adding rows — no call site changes required.
_ALIASES = {
    # Precious metals (spot names -> COMEX/NYMEX futures)
    "XAUUSD": "GC=F", "XAU": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    # Energy
    "WTICOUSD": "CL=F", "USOIL": "CL=F", "WTI": "CL=F",
    "BCOUSD": "BZ=F", "UKOIL": "BZ=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "XNGUSD": "NG=F",
    "COPPER": "HG=F", "XCUUSD": "HG=F",
    # Index CFDs -> Westock index symbols
    "SPX500": "^GSPC", "US500": "^GSPC", "SPX": "^GSPC",
    "NAS100": "^NDX", "US100": "^NDX", "USTEC": "^NDX",
    "US30": "^DJI", "DJI30": "^DJI", "WS30": "^DJI",
    "GER40": "^GDAXI", "GER30": "^GDAXI", "DE40": "^GDAXI",
    "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "HK50": "^HSI",
}

# Westock symbols may contain letters, digits, and these structural characters.
_WESTOCK_SAFE = re.compile(r"^[A-Za-z0-9._\-\^=]+$")


# Crypto quote currencies that all map to Westock's USD pair. Westock lists only
# ``<BASE>-USD`` (not the USDT/USDC stablecoin pairs), so a broker symbol quoted
# in any of these resolves to ``-USD`` (#982). Longest first so ``USDT``/``USDC``
# match before the ``USD`` substring.
_CRYPTO_QUOTES = ("USDT", "USDC", "USD")


def _normalize_crypto(s: str) -> str | None:
    """Return ``<BASE>-USD`` if ``s`` is a known crypto quoted in USD/USDT/USDC.

    Accepts dashed or undashed forms: ``BTCUSD``, ``BTCUSDT``, ``BTC-USDT``,
    ``BTC-USDC`` all resolve to ``BTC-USD``. Returns None otherwise.
    """
    compact = s.replace("-", "")
    for quote in _CRYPTO_QUOTES:
        if compact.endswith(quote):
            base = compact[: -len(quote)]
            if base in _CRYPTO_BASES:
                return f"{base}-USD"
            break
    return None


def normalize_symbol(raw: str) -> str:
    """Map a user/broker symbol to its canonical Westock symbol.

    Resolution order (first match wins):
      1. Explicit alias table (metals, energy, index CFDs).
      2. Crypto rule: a known crypto base quoted in USD/USDT/USDC (dashed or
         not) -> ``BASE-USD``.
      3. Forex rule: six letters that are two ISO currency codes -> ``PAIR=X``.
      4. Otherwise the upper-cased symbol is returned unchanged (plain
         equities, ETFs, Westock-native symbols like ``GC=F`` or ``^GSPC``).

    A trailing ``+`` (broker CFD marker, e.g. ``XAUUSD+``) is stripped before
    matching. The function is purely syntactic — it performs no network
    calls — so it is safe to apply on every request.
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw

    s = raw.strip().upper()
    # Broker CFD/qualifier suffixes Westock never uses.
    s = s.rstrip("+")

    crypto = _normalize_crypto(s)
    if s in _ALIASES:
        canonical = _ALIASES[s]
    elif crypto is not None:
        canonical = crypto
    elif len(s) == 6 and s[:3] in _FOREX_CURRENCIES and s[3:] in _FOREX_CURRENCIES:
        canonical = f"{s}=X"
    else:
        canonical = s

    if canonical != raw.strip().upper():
        logger.info("Resolved symbol %r to Westock symbol %r", raw, canonical)
    return canonical


def is_westock_safe(symbol: str) -> bool:
    """True when ``symbol`` only contains characters Westock symbols use."""
    return bool(symbol) and _WESTOCK_SAFE.fullmatch(symbol) is not None


_SOCIAL_TICKER_MAP = {
    "0700.HK": {"stocktwits": "TCEHY", "reddit": "Tencent OR TCEHY", "news_query": "Tencent"},
    "9988.HK": {"stocktwits": "BABA", "reddit": "Alibaba OR BABA", "news_query": "Alibaba"},
    "3690.HK": {"stocktwits": "MPNGF", "reddit": "Meituan", "news_query": "Meituan"},
    "1810.HK": {"stocktwits": "XIACY", "reddit": "Xiaomi", "news_query": "Xiaomi"},
    "9888.HK": {"stocktwits": "BIDU", "reddit": "Baidu OR BIDU", "news_query": "Baidu"},
    "9618.HK": {"stocktwits": "JD", "reddit": "JD.com OR JD", "news_query": "JD.com"},
    "9999.HK": {"stocktwits": "NTES", "reddit": "NetEase OR NTES", "news_query": "NetEase"},
    "1211.HK": {"stocktwits": "BYDDY", "reddit": "BYD OR BYDDY", "news_query": "BYD"},
    "0981.HK": {"stocktwits": "SMICY", "reddit": "SMIC", "news_query": "SMIC"},
}


def clean_company_name(name: str) -> str:
    """Clean company names for search queries by removing common corporate suffixes."""
    if not name:
        return ""
    # Remove common suffixes case-insensitively
    suffixes = [
        r"\bcorp(?:oration)?\b",
        r"\binc(?:orporated)?\b",
        r"\bltd\b",
        r"\blimited\b",
        r"\bplc\b",
        r"\bco\b",
        r"\bholdings?\b",
        r"\bs\.a\b",
        r"\ba\.g\b",
    ]
    cleaned = name
    for pattern in suffixes:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    # Strip non-alphanumeric/spaces/dots
    cleaned = re.sub(r"[^\w\s.-]", "", cleaned)
    # Collapse multiple spaces
    cleaned = " ".join(cleaned.split())
    return cleaned.strip()


def resolve_social_query(symbol: str) -> dict[str, str]:
    """Map a ticker to its social media / news search terms.

    Returns a dict with keys:
      - 'stocktwits': Symbol to use for StockTwits stream.
      - 'reddit': Search query to use for Reddit search.
      - 'news_query': Text query to use for news search.
    """
    sym = symbol.upper().strip()
    if sym in _SOCIAL_TICKER_MAP:
        return _SOCIAL_TICKER_MAP[sym]

    # Defaults: clean up ticker or strip exchange suffixes
    base_sym = sym.partition(".")[0]
    return {
        "stocktwits": base_sym,
        "reddit": sym,
        "news_query": base_sym,
    }


def to_westock_code(symbol: str) -> str:
    """Convert standard TradingAgents symbol format to westock format.

    e.g. 
      0700.HK -> hk00700
      NVDA -> usNVDA
      600519.SH -> sh600519
      000001.SZ -> sz000001
      300750.SZ -> sz300750
    """
    if not symbol:
        return ""
    s = normalize_symbol(symbol).upper().strip()
    # Remove CFD trailing qualifier if any
    s = s.rstrip("+")
    # If already in westock format (e.g. sh600519, hk00700, usAAPL)
    if (s.startswith("SH") or s.startswith("SZ") or s.startswith("BJ") or s.startswith("HK") or s.startswith("US")) and s[2:].isalnum():
        return s.lower()

    # Check HK
    if s.endswith(".HK"):
        num = s[:-3].zfill(5)
        return f"hk{num}"
    # Check A-shares
    if s.endswith(".SH"):
        return f"sh{s[:-3]}"
    if s.endswith(".SZ"):
        return f"sz{s[:-3]}"
    if s.endswith(".BJ"):
        return f"bj{s[:-3]}"

    # Check standard US equities
    if s.isalpha():
        return f"us{s}"

    # Default fallback
    return s.lower()


WESTOCK_SCRIPT = "/data/hermes/skills/westock-data/scripts/index.js"


def is_westock_available() -> bool:
    """Return True if westock-data skill exists on this machine."""
    import os
    return os.path.exists(WESTOCK_SCRIPT)


def run_westock(args: list[str], raw: bool = True) -> str:
    """Execute a westock-data command and return the stdout as a string.

    If raw is True, appends --raw to get structured output.
    """
    import subprocess
    if not is_westock_available():
        raise RuntimeError("westock-data skill is not available on this machine.")
    cmd = ["node", WESTOCK_SCRIPT] + args
    if raw and "--raw" not in args:
        cmd.append("--raw")
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return res.stdout
    except subprocess.CalledProcessError as e:
        logger.error("westock command failed: %s\nStdout: %s\nStderr: %s", e, e.stdout, e.stderr)
        raise RuntimeError(f"westock-data failed: {e.stderr or e.stdout or str(e)}")

