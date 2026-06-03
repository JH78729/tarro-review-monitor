"""
Tarro Review Monitor — daily scraper
- Google search scrape (no API key needed)
- YouTube search scrape (titles + descriptions, no API key needed)
- Reddit public API (no key needed)
"""
import json, os, re, time, hashlib
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
REVIEWS_FILE = DATA_DIR / "reviews.json"
META_FILE    = DATA_DIR / "meta.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

GOOGLE_QUERIES = [
    "食客通 评价", "食客通 餐厅", "食客通 差评", "食客通 好用",
    "Tarro restaurant review", "Tarro phone ordering chinese restaurant",
    "wondersco tarro", "食客通 tarro",
]

YOUTUBE_QUERIES = [
    "食客通", "Tarro restaurant", "tarro phone ordering",
    "中餐厅电话系统", "食客通 餐厅",
]

REDDIT_QUERIES = [
    ("tarro restaurant", "all"),
    ("tarro phone ordering", "all"),
    ("食客通", "all"),
    ("chinese restaurant phone answering service", "ChineseFood+restaurants"),
]

def make_id(*parts):
    return hashlib.md5(":".join(str(p) for p in parts).encode()).hexdigest()[:16]

def load_existing():
    if REVIEWS_FILE.exists():
        return json.loads(REVIEWS_FILE.read_text())
    return []

def dedup(reviews):
    seen, out = set(), []
    for r in reviews:
        k = r.get("id", "")
        if k and k not in seen:
            seen.add(k); out.append(r)
    return out

def tarro_mentioned(text):
    return bool(re.search(r"tarro|食客通|wondersco", text, re.I))

def competitor_mentioned(text):
    return bool(re.search(r"otter|popmenu|toast pos|square pos|clover|grubhub|ubereats|doordash", text, re.I))

def simple_sentiment(text, rating=None):
    if rating:
        return "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
    p = len(re.findall(r"好|棒|赞|推荐|省事|helpful|great|love|excellent|amazing|fantastic", text, re.I))
    n = len(re.findall(r"差|烂|垃圾|贵|骗|口音|bad|terrible|awful|expensive|scam|rude|worst|horrible", text, re.I))
    return "positive" if p > n else "negative" if n > p else "neutral"

def categorize(text):
    if re.search(r"价格|贵|price|expensive|cost|收费", text, re.I): return "价格投诉"
    if re.search(r"口音|accent|接线|hold|wait|听不懂|慢", text, re.I): return "服务问题"
    if re.search(r"垃圾|骗|spam|scam|fraud|恶意|假评", text, re.I): return "恶意差评"
    if re.search(r"功能|feature|建议|suggest|improve|希望", text, re.I): return "功能建议"
    if re.search(r"推荐|好用|recommend|love|great|省事|帮助|方便", text, re.I): return "好评"
    if competitor_mentioned(text): return "竞品提及"
    return "其他"

def make_review(platform, source, author, date, text, url="", rating=None):
    return {
        "id":             make_id(platform, source, text[:40]),
        "platform":       platform,
        "source_name":    source,
        "author":         author,
        "date":           date,
        "rating":         rating,
        "text":           text.strip()[:600],
        "url":            url,
        "mentions_tarro": tarro_mentioned(text),
        "is_competitor":  competitor_mentioned(text),
        "sentiment":      simple_sentiment(text, rating),
        "category":       categorize(text),
        "manual":         False,
        "fetched_at":     datetime.now(timezone.utc).isoformat(),
    }

# ── Google Search ─────────────────────────────────────────────────────────────
def fetch_google():
    results = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for q in GOOGLE_QUERIES:
        url = f"https://www.google.com/search?q={requests.utils.quote(q)}&num=10&hl=zh-TW"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(resp.text, "lxml")
            for g in soup.select("div.g, div[data-hveid]"):
                title_el   = g.select_one("h3")
                snippet_el = g.select_one("div.VwiC3b, span.st, div[data-sncf]")
                link_el    = g.select_one("a[href]")
                if not title_el: continue
                title   = title_el.get_text(" ", strip=True)
                snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
                link    = link_el.get("href", "") if link_el else ""
                if link.startswith("/url?q="):
                    link = link.split("/url?q=")[1].split("&")[0]
                text = f"{title} {snippet}".strip()
                if len(text) < 20: continue
                if not tarro_mentioned(text) and not competitor_mentioned(text): continue
                domain = re.sub(r"https?://([^/]+).*", r"\1", link) if link else "google"
                results.append(make_review("Web", domain, "", today, text, link))
            time.sleep(2)
        except Exception as e:
            print(f"  [Google] Error '{q}': {e}")
    print(f"  [Google] {len(results)} results")
    return results

# ── YouTube Search ────────────────────────────────────────────────────────────
def fetch_youtube():
    results = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for q in YOUTUBE_QUERIES:
        url = f"https://www.youtube.com/results?search_query={requests.utils.quote(q)}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            # YouTube embeds JSON data in the page
            match = re.search(r'var ytInitialData = ({.*?});</script>', resp.text, re.DOTALL)
            if not match:
                print(f"  [YouTube] No data for '{q}'")
                continue
            data = json.loads(match.group(1))
            # navigate to video results
            contents = (data.get("contents", {})
                           .get("twoColumnSearchResultsRenderer", {})
                           .get("primaryContents", {})
                           .get("sectionListRenderer", {})
                           .get("contents", []))
            for section in contents:
                items = (section.get("itemSectionRenderer", {})
                                .get("contents", []))
                for item in items:
                    v = item.get("videoRenderer", {})
                    if not v: continue
                    title = "".join(r.get("text","") for r in v.get("title",{}).get("runs",[]))
                    desc  = "".join(r.get("text","") for r in v.get("descriptionSnippet",{}).get("runs",[]))
                    vid_id = v.get("videoId","")
                    text = f"{title} {desc}".strip()
                    if not text or len(text) < 10: continue
                    if not tarro_mentioned(text) and not competitor_mentioned(text): continue
                    results.append(make_review(
                        platform="YouTube",
                        source="YouTube",
                        author=v.get("ownerText",{}).get("runs",[{}])[0].get("text",""),
                        date=today,
                        text=text,
                        url=f"https://www.youtube.com/watch?v={vid_id}" if vid_id else url,
                    ))
            time.sleep(1.5)
        except Exception as e:
            print(f"  [YouTube] Error '{q}': {e}")
    print(f"  [YouTube] {len(results)} relevant videos")
    return results

# ── Reddit ────────────────────────────────────────────────────────────────────
def fetch_reddit():
    results = []
    for q, sub in REDDIT_QUERIES:
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {"q": q, "sort": "new", "limit": 25, "t": "year"}
        if sub != "all":
            params["restrict_sr"] = True
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"},
                                params=params, timeout=15)
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for p in posts:
                d = p.get("data", {})
                title    = d.get("title", "")
                selftext = d.get("selftext", "")
                text     = f"{title} {selftext}".strip()
                if not tarro_mentioned(text) and not competitor_mentioned(text): continue
                created = datetime.fromtimestamp(d.get("created_utc", 0), tz=timezone.utc)
                results.append(make_review(
                    platform="Reddit",
                    source=f"r/{d.get('subreddit','')}",
                    author=d.get("author", ""),
                    date=created.strftime("%Y-%m-%d"),
                    text=text[:600],
                    url=f"https://reddit.com{d.get('permalink','')}",
                ))
            time.sleep(1)
        except Exception as e:
            print(f"  [Reddit] Error '{q}': {e}")
    print(f"  [Reddit] {len(results)} relevant posts")
    return results

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*55}\nTarro Review Monitor — {now.strftime('%Y-%m-%d %H:%M UTC')}\n{'='*55}")

    existing = load_existing()
    manual   = [r for r in existing if r.get("manual")]
    print(f"Existing: {len(existing)} total, {len(manual)} manual kept\n")

    new_reviews = []
    print("→ Google Search...")
    new_reviews.extend(fetch_google())
    print("\n→ YouTube...")
    new_reviews.extend(fetch_youtube())
    print("\n→ Reddit...")
    new_reviews.extend(fetch_reddit())

    all_reviews = dedup(manual + new_reviews)
    all_reviews.sort(key=lambda r: r.get("date", ""), reverse=True)
    REVIEWS_FILE.write_text(json.dumps(all_reviews, ensure_ascii=False, indent=2))

    t   = len(all_reviews)
    pos = sum(1 for r in all_reviews if r["sentiment"] == "positive")
    neg = sum(1 for r in all_reviews if r["sentiment"] == "negative")
    men = sum(1 for r in all_reviews if r.get("mentions_tarro"))
    by_plat = {}
    for r in all_reviews:
        by_plat[r["platform"]] = by_plat.get(r["platform"], 0) + 1

    META_FILE.write_text(json.dumps({
        "last_run": now.isoformat(), "total": t,
        "positive": pos, "negative": neg, "neutral": t-pos-neg,
        "mentions_tarro": men,
        "positive_pct": round(pos/t*100,1) if t else 0,
        "negative_pct": round(neg/t*100,1) if t else 0,
        "by_platform": by_plat,
    }, ensure_ascii=False, indent=2))

    print(f"\n✓ {t} total | +{pos} pos -{neg} neg | {men} mention Tarro")
    print(f"  Platforms: {by_plat}")

if __name__ == "__main__":
    main()
