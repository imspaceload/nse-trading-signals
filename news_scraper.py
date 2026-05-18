from typing import List

import requests
from bs4 import BeautifulSoup

from config import MONEYCONTROL_URL, NEWS_COUNT

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

BULLISH_KEYWORDS = [
    "rally", "surge", "jump", "gain", "rise", "bull", "buy", "up",
    "record high", "breakout", "positive", "boom", "soar", "advance",
    "recovery", "strong", "outperform", "upgrade",
]
BEARISH_KEYWORDS = [
    "fall", "drop", "crash", "decline", "sell", "bear", "down",
    "low", "loss", "weak", "slip", "tank", "plunge", "drag",
    "correction", "downgrade", "fear", "risk",
]


def classify_sentiment(headline: str) -> str:
    lower = headline.lower()
    bull_score = sum(1 for kw in BULLISH_KEYWORDS if kw in lower)
    bear_score = sum(1 for kw in BEARISH_KEYWORDS if kw in lower)
    if bull_score > bear_score:
        return "BULLISH"
    elif bear_score > bull_score:
        return "BEARISH"
    return "NEUTRAL"


def scrape_moneycontrol_news() -> List[dict]:
    try:
        resp = requests.get(MONEYCONTROL_URL, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        articles = []
        for tag in soup.select("li.clearfix"):
            link_tag = tag.select_one("h2 a") or tag.select_one("a")
            if not link_tag:
                continue
            title = link_tag.get_text(strip=True)
            url = link_tag.get("href", "")
            if not title or not url:
                continue
            articles.append({
                "headline": title,
                "url": url,
                "source": "Moneycontrol",
                "sentiment": classify_sentiment(title),
            })
            if len(articles) >= NEWS_COUNT:
                break

        if not articles:
            for tag in soup.find_all("a", href=True):
                title = tag.get_text(strip=True)
                url = tag["href"]
                if (
                    len(title) > 30
                    and "moneycontrol.com/news" in url
                    and title not in [a["headline"] for a in articles]
                ):
                    articles.append({
                        "headline": title,
                        "url": url,
                        "source": "Moneycontrol",
                        "sentiment": classify_sentiment(title),
                    })
                    if len(articles) >= NEWS_COUNT:
                        break

        return articles
    except Exception as e:
        return [{"headline": f"Failed to fetch news: {e}", "url": "", "source": "Error", "sentiment": "NEUTRAL"}]
