from __future__ import annotations
import os
from dataclasses import dataclass
from typing import List

DEFAULT_PAID_UNIVERSE = [
    "AAPL","MSFT","NVDA","TSLA","AMD","META","AMZN","GOOGL","GOOG","PLTR","SMCI","AVGO",
    "NFLX","CRM","ORCL","ADBE","SHOP","COIN","HOOD","SOFI","MARA","RIOT","RIVN","LCID",
    "NIO","XPEV","LI","BABA","UBER","LYFT","AFRM","UPST","OPEN","ROKU","SNOW","DDOG",
    "NET","CRWD","PANW","ZS","SOUN","BBAI","AI","IONQ","QBTS","ACHR","JOBY","RKLB",
    "ASTS","LUNR","GME","AMC","CVNA","BYND","FUBO","DNA","LAZR","ENVX","MSTR","CLSK",
    "WULF","HIMS","CELH","DKNG","RBLX","U","PATH","PINS","SNAP","DIS","BA","GE","F","GM",
    "XOM","CVX","OXY","CCL","NCLH","DAL","AAL"
]

@dataclass(frozen=True)
class AlpacaPaidSettings:
    feed: str
    max_symbols: int
    chunk_size: int
    bar_timeframe: str
    lookback_minutes: int
    baseline_days: int
    include_news: bool
    news_lookback_hours: int
    news_limit: int
    use_sip: bool


def get_paid_settings() -> AlpacaPaidSettings:
    feed = os.getenv("ALPACA_DATA_FEED", "sip").lower().strip()
    if feed not in {"sip", "iex"}:
        feed = "sip"
    return AlpacaPaidSettings(
        feed=feed,
        use_sip=feed == "sip",
        max_symbols=int(os.getenv("ALPACA_MAX_SYMBOLS", "500")),
        chunk_size=int(os.getenv("ALPACA_CHUNK_SIZE", "100")),
        bar_timeframe=os.getenv("ALPACA_BAR_TIMEFRAME", "1Min"),
        lookback_minutes=int(os.getenv("ALPACA_LOOKBACK_MINUTES", "390")),
        baseline_days=int(os.getenv("ALPACA_RVOL_BASELINE_DAYS", "20")),
        include_news=os.getenv("ALPACA_NEWS_ENABLED", "true").lower() == "true",
        news_lookback_hours=int(os.getenv("ALPACA_NEWS_LOOKBACK_HOURS", "24")),
        news_limit=int(os.getenv("ALPACA_NEWS_LIMIT", "50")),
    )


def get_universe() -> List[str]:
    raw = os.getenv("ALPACA_SYMBOL_UNIVERSE", "").strip()
    if raw:
        symbols = [x.strip().upper() for x in raw.split(",") if x.strip()]
        if symbols:
            return symbols
    return DEFAULT_PAID_UNIVERSE
