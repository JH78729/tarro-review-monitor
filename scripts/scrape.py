"""
Tarro Review Monitor — daily scraper
Sources:
  1. Google Custom Search (mentions of 食客通 / Tarro)
  2. Reddit (pushshift/public search)
  3. Yelp public pages (HTML scrape, no API key needed)
  4. Google Places API (reviews, needs API key)
"""

import json, os, re, time, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
REVIEWS_FILE = DATA_DIR / "reviews.json"
META_FILE    = DATA_DIR / "meta.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# ── env ───────────────────────────────────────────────────────────────────────
GOOGLE_API_KEY    = os.environ.get("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID     = os.environ.get("GOOGLE_CSE_ID", "")       # Custom Search Engine ID
GOOGLE_PLACE_IDS  = [p.strip() for p in os.environ.get("GOOGLE_PLACE_IDS","").split(",") if p.strip()]
YELP_URLS         = [u.strip() for u in os.environ.get("YELP_URLS","").split(",") if u.strip()]
# fallback public Yelp searches if no specific URLs given
YELP_SEARCH_QUERIES = ["tarro restaurant phone ordering", "食客通 restaurant"]

SEARCH_KEYWORDS = [
    "食客通 评价", "食客通 review", "食客通 好用吗",
    "Tarro restaurant phone ordering review",
    "Tarro wondersco restaurant review",
    "食客通 餐厅",
]

# ── helpers ───────────────────────────────────────────────────────────────────
def load_existing() -> list[dict]:
    if REVIEWS_FILE.exists():
        return json.loads(REVIEWS_FILE.read_text())
    return []

def make_id(*parts) -> str:
    return hashlib.md5(":".join(str(p) for p in parts).encode()).hexdigest()[:16]

def dedup(reviews: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in reviews:
        k = r.get("id", "")
        if k and k not in seen:
            seen.add(k); out.append(r)
    return out

def tarro_mentioned(text: str) -> bool:
    return bool(re.search(r"tarro|食客通|wondersco", text, re.I))

def simple_sentiment(text: str, rating=None) -> str:
    if rating is not None:
        return "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
    pos = len(re.findall(r"好|棒|赞|推荐|省事|方便|great|love|excellent|perfect|amazing|helpful", text, re.I))
    neg = len(re.findall(r"差|烂|垃圾|贵|骗|口音|问题|bad|terrible|awful|expensive|scam|rude|slow", text, re.I))
    return "positive" if pos > neg else "negative" if neg > pos else "neutral"

def categorize(text: str) -> str:
    t = text.lower()
    if re.search(r"价格|贵|price|expensive|cost|收费", t): return "价格投诉"
    if re.search(r"口音|accent|接线|phone|hold|wait|啰嗦|重复", t): return "服务问题"
    if re.search(r"垃圾|骗|spam|scam|garbage|fraud|恶意|假", t): return "恶意差评"
    if re.search(r"功能|feature|建议|suggest|improve|希望", t): return "功能建议"
    if re.search(r"推荐|好用|recommend|love|great|省事|帮助", t): return "好评"
    return "其他"

def make_review(platform, source, author, date, text, url="", rating=None, manual=False) -> dict:
    return {
        "id":            make_id(platform, source, author, date, text[:40]),
        "platform":      platform,
        "source_name":   source,
        "author":        author,
        "date":          date,
        "rating":        rating,
        "text":          text.strip(),
        "url":           url,
        "mentions_tarro": tarro_mentioned(text),
        "sentiment":     simple_sentiment(text, rating),
        "category":      categorize(text),
        "manual":        manual,
        "fetched_at":    datetime.now(timezone.utc).isoformat(),
    }

# ── 1. Google Custom Search ───────────────────────────────────────────────────
def fetch_google_search() -> list[dict]:
    """
    Uses Google Custom Search JSON API (free tier: 100 queries/day).
    Needs GOOGLE_API_KEY + GOOGLE_CSE_ID (set up at cse.google.com).
    Falls back to SerpAPI-style scrape if no key.
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("  [Google Search] No CSE key — skipping (set GOOGLE_API_KEY + GOOGLE_CSE_ID)")
        return []

    results = []
    for kw in SEARCH_KEYWORDS[:4]:   # stay within free quota
        url = "https://www.googleapis.com/customsearch/v1"
        params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_ID, "q": kw, "num": 10}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            items = resp.json().get("items", [])
            for item in items:
                snippet = item.get("snippet", "")
                title   = item.get("title", "")
                link    = item.get("link", "")
                text    = f"{title} — {snippet}"
                if not tarro_mentioned(text):
                    continue
                results.append(make_review(
                    platform="Web",
                    source=item.get("displayLink", "web"),
                    author="",
                    date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    text=text,
                    url=link,
                ))
            time.sleep(0.3)
        except Exception as e:
            print(f"  [Google Search] Error for '{kw}': {e}")

    print(f"  [Google Search] {len(results)} mentions found")
    return results

# ── 2. Reddit ─────────────────────────────────────────────────────────────────
def fetch_reddit() -> list[dict]:
    """
    Uses Reddit's public JSON search endpoint (no auth required).
    Searches relevant subreddits for Tarro / 食客通 mentions.
    """
    queries = [
        ("tarro restaurant", "all"),
        ("食客通", "all"),
        ("tarro phone ordering", "ChineseFood+restaurants+smallbusiness"),
    ]
    results = []
    for q, sub in queries:
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {"q": q, "sort": "new", "limit": 25, "t": "year", "restrict_sr": sub != "all"}
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, params=params, timeout=15)
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for p in posts:
                d = p.get("data", {})
                title    = d.get("title", "")
                selftext = d.get("selftext", "")
                text     = f"{title} {selftext}".strip()
                if not tarro_mentioned(text):
                    continue
                created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
                results.append(make_review(
                    platform="Reddit",
                    source=f"r/{d.get('subreddit','')}",
                    author=d.get("author", ""),
                    date=created.strftime("%Y-%m-%d"),
                    text=text[:500],
                    url=f"https://reddit.com{d.get('permalink','')}",
                    rating=None,
                ))
            # also fetch top-level comments from relevant posts
            time.sleep(0.5)
        except Exception as e:
            print(f"  [Reddit] Error for '{q}': {e}")

    print(f"  [Reddit] {len(results)} mentions found")
    return results

# ── 3. Yelp public scrape ─────────────────────────────────────────────────────
def scrape_yelp_page(url: str) -> list[dict]:
    """Scrape public Yelp business reviews page (HTML, no API key)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        reviews = []

        # Yelp review cards (class names change periodically — match loosely)
        for card in soup.select("[class*='review__'] li, [data-testid='review'], li[class*='css-']"):
            # text
            p_tags = card.select("p[lang], span[class*='raw__']")
            text = " ".join(t.get_text(" ", strip=True) for t in p_tags)
            if not text or len(text) < 10:
                continue
            # rating
            rating = None
            star_el = card.select_one("[aria-label*='star']")
            if star_el:
                m = re.search(r"(\d)", star_el.get("aria-label", ""))
                if m: rating = int(m.group(1))
            # author + date
            author_el = card.select_one("a[href*='/user_details']")
            author = author_el.get_text(strip=True) if author_el else ""
            date_el = card.select_one("span[class*='date'], [class*='css-chan6m']")
            date_str = date_el.get_text(strip=True) if date_el else ""
            try:
                dt = datetime.strptime(date_str, "%m/%d/%Y")
                date_iso = dt.strftime("%Y-%m-%d")
            except Exception:
                date_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            reviews.append(make_review(
                platform="Yelp",
                source=url.split("/biz/")[-1].split("?")[0] if "/biz/" in url else url,
                author=author,
                date=date_iso,
                text=text,
                url=url,
                rating=rating,
            ))
        return reviews
    except Exception as e:
        print(f"  [Yelp scrape] Error {url}: {e}")
        return []

def fetch_yelp() -> list[dict]:
    urls = YELP_URLS if YELP_URLS else []
    # also try searching Yelp for Tarro directly
    for q in YELP_SEARCH_QUERIES:
        search_url = f"https://www.yelp.com/search?find_desc={quote_plus(q)}&find_loc=United+States"
        try:
            resp = requests.get(search_url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("a[href*='/biz/']")[:3]:
                href = a.get("href", "")
                biz_url = "https://www.yelp.com" + href if href.startswith("/biz/") else href
                if biz_url not in urls:
                    urls.append(biz_url)
            time.sleep(0.5)
        except Exception as e:
            print(f"  [Yelp search] Error: {e}")

    all_reviews = []
    for url in urls[:5]:
        r = scrape_yelp_page(url)
        print(f"  [Yelp] {url}: {len(r)} reviews")
        all_reviews.extend(r)
        time.sleep(1)

    # keep only those mentioning Tarro OR all reviews if from known Tarro biz page
    relevant = [r for r in all_reviews if r["mentions_tarro"]]
    print(f"  [Yelp] {len(relevant)} Tarro-relevant reviews total")
    return relevant

# ── 4. Google Places API (reviews) ───────────────────────────────────────────
def fetch_google_places() -> list[dict]:
    if not GOOGLE_API_KEY or not GOOGLE_PLACE_IDS:
        print("  [Google Places] No API key or Place IDs — skipping")
        return []
    reviews = []
    for place_id in GOOGLE_PLACE_IDS:
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {"place_id": place_id, "fields": "name,reviews",
                  "language": "zh-TW", "reviews_sort": "newest", "key": GOOGLE_API_KEY}
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            result = resp.json().get("result", {})
            name = result.get("name", place_id)
            for r in result.get("reviews", []):
                text   = r.get("text", "")
                rating = r.get("rating")
                created = datetime.fromtimestamp(r.get("time", 0), tz=timezone.utc)
                reviews.append(make_review(
                    platform="Google Reviews",
                    source=name,
                    author=r.get("author_name", ""),
                    date=created.strftime("%Y-%m-%d"),
                    text=text,
                    url=r.get("author_url", ""),
                    rating=rating,
                ))
            print(f"  [Google Places] {name}: {len(result.get('reviews',[]))} reviews")
        except Exception as e:
            print(f"  [Google Places] Error {place_id}: {e}")
    return reviews

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*55}")
    print(f"Tarro Review Monitor — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*55}")

    existing = load_existing()
    # preserve manual entries
    manual = [r for r in existing if r.get("manual")]
    print(f"Existing: {len(existing)} total, {len(manual)} manual entries kept\n")

    new_reviews = []

    print("→ Google Custom Search...")
    new_reviews.extend(fetch_google_search())

    print("\n→ Reddit...")
    new_reviews.extend(fetch_reddit())

    print("\n→ Yelp...")
    new_reviews.extend(fetch_yelp())

    print("\n→ Google Places API...")
    new_reviews.extend(fetch_google_places())

    all_reviews = dedup(manual + new_reviews)
    all_reviews.sort(key=lambda r: r.get("date", ""), reverse=True)

    REVIEWS_FILE.write_text(json.dumps(all_reviews, ensure_ascii=False, indent=2))
    print(f"\n✓ Saved {len(all_reviews)} reviews → data/reviews.json")

    t   = len(all_reviews)
    pos = sum(1 for r in all_reviews if r["sentiment"] == "positive")
    neg = sum(1 for r in all_reviews if r["sentiment"] == "negative")
    men = sum(1 for r in all_reviews if r.get("mentions_tarro"))

    by_plat = {}
    for r in all_reviews:
        by_plat[r["platform"]] = by_plat.get(r["platform"], 0) + 1

    meta = {
        "last_run":       now.isoformat(),
        "total":          t,
        "positive":       pos,
        "negative":       neg,
        "neutral":        t - pos - neg,
        "mentions_tarro": men,
        "positive_pct":   round(pos / t * 100, 1) if t else 0,
        "negative_pct":   round(neg / t * 100, 1) if t else 0,
        "by_platform":    by_plat,
    }
    META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    print(f"✓ Meta: +{pos} pos  -{neg} neg  {men} mention Tarro")
    print(f"  Platforms: {by_plat}")

if __name__ == "__main__":
    main()
