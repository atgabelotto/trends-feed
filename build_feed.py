#!/usr/bin/env python3
"""Build a daily social-trends RSS 2.0 feed from a normalized items JSON file.

Usage: python3 build_feed.py items.json feed.xml

Input item fields (all strings unless noted):
  platform: instagram | tiktok | pinterest
  creator: handle / account name
  title: plain-words trend name, e.g. "Stuffed onions with noodles"
  link: original post / source URL (also used as guid, so it must be stable)
  posted: ISO date of the original post, e.g. 2026-10-30
  engagement: human-readable figures actually seen on the source, e.g. "150K likes"
             (leave empty if unverified -- the item is then flagged, not invented)
  verified: bool -- engagement figures were seen live / via a connector
  sound: sound / track name, if any
  format: dance | food | comedy | culture | beauty | other
  client_tags: list of client tags, e.g. ["ontario-beef"] -- tags only, never a filter
  virality: int 1-5 -- engagement relative to creator size + reach beyond its niche
  growth_rate: int 1-5 -- how fast engagement / posts using it are climbing in 24h
  sentiment: int 1-5 -- audience reception: 5 = overwhelmingly positive,
             3 = mixed, 1 = backlash / negative (a backlash trend ranks low
             even if it is viral, unless the user explicitly asks otherwise)
  summary: one or two sentences on what it is and why it matters

Collection target: at least MIN_CANDIDATES (100) options are pulled per day
across Instagram, TikTok and Pinterest before ranking. If fewer arrive
(e.g. a platform blocks), the run still publishes but logs a shortfall
warning -- a blocked leg must never silently pass as a quiet day.

Ranking: score = virality + growth_rate + sentiment (max 15), ties broken
by posted date (newest first).

Buckets (added Oct 30, 2026, per the user's rule):
  first_seen: ISO date the trend was FIRST seen in a daily candidate pool.
    If absent, the trend counts as new today.
  age = build date (UTC) - first_seen, in days.
    age <= 7 days  -> New, capped at MAX_NEW (25)
    8–14 days and still in today's pool -> Signal, capped at MAX_SIGNAL (5)
    15–21 days and still in today's pool -> Evergreen, capped at MAX_EVERGREEN (5)
    age > 21 days  -> EXPIRED, dropped even if still trending.
  A trend that misses a daily pool resets: its first_seen becomes the date
  it reappears, so a dead trend cannot resurrect as a Signal/Evergreen.
  Total feed size is therefore at most 25 + 5 + 5 = 35 items.
  Each bucket is ranked by score independently, so Signals/Evergreens never
  push new trends out of the 25, and vice versa.

Nothing here scrapes, posts, contacts a creator, or buys anything. Collection
is a separate step; this script only normalizes, ranks, caps and validates.
"""
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

MAX_NEW = 25
MAX_SIGNAL = 5
MAX_EVERGREEN = 5
MAX_ITEMS = MAX_NEW + MAX_SIGNAL + MAX_EVERGREEN  # 35
MIN_CANDIDATES = 100
FEED_TITLE = "Daily Social Trends"
FEED_LINK = "https://atgabelotto.github.io/trends-feed/"  # GitHub Pages URL once enabled
FEED_DESC = (
    "Daily raw social trends across Instagram, TikTok and Pinterest, "
    "whittled from 100+ candidates to 25 new trends by virality, growth rate "
    "and sentiment, plus up to 5 Signals (still trending after 1 week) and "
    "up to 5 Evergreens (still trending after 2 weeks, expiring after 3 weeks). "
    "Client tags are filters for the reader, not a filter on the feed."
)


def score(item):
    return (
        int(item.get("virality", 0))
        + int(item.get("growth_rate", 0))
        + int(item.get("sentiment", 0))
    )


def to_rfc822(iso_date):
    dt = datetime.fromisoformat(iso_date).replace(tzinfo=timezone.utc)
    return format_datetime(dt)


def main():
    items_path, out_path = sys.argv[1], sys.argv[2]
    with open(items_path) as f:
        items = json.load(f)
    if len(items) < MIN_CANDIDATES:
        print(
            f"WARNING: only {len(items)} candidates pulled, "
            f"target is {MIN_CANDIDATES}+ -- shortfall must be logged in the run log",
            file=sys.stderr,
        )

    # Validate required fields; drop (loudly) anything incomplete.
    good = []
    for it in items:
        missing = [k for k in ("platform", "creator", "title", "link", "posted") if not it.get(k)]
        if missing:
            print(f"SKIP (missing {','.join(missing)}): {it.get('link', it)}", file=sys.stderr)
            continue
        good.append(it)

    # Bucket by age from first_seen, relative to today's UTC date.
    from datetime import date as _date

    today = datetime.now(timezone.utc).date()
    buckets = {"New": [], "Signal": [], "Evergreen": []}
    for it in good:
        fs = it.get("first_seen")
        try:
            age = (today - _date.fromisoformat(fs)).days if fs else 0
        except ValueError:
            age = 0
        it["_age"] = age
        if age > 21:
            print(f"EXPIRED (age {age}d, >21d): {it['title']}", file=sys.stderr)
            continue
        elif age >= 15:
            it["_bucket"] = "Evergreen"
        elif age >= 8:
            it["_bucket"] = "Signal"
        else:
            it["_bucket"] = "New"
        buckets[it["_bucket"]].append(it)

    def rank(bucket_items):
        # Score desc, then newest posted first, stable within ties.
        bucket_items.sort(key=lambda it: it["posted"], reverse=True)
        bucket_items.sort(key=lambda it: -score(it))
        return bucket_items

    ordered = (
        rank(buckets["New"])[:MAX_NEW]
        + rank(buckets["Signal"])[:MAX_SIGNAL]
        + rank(buckets["Evergreen"])[:MAX_EVERGREEN]
    )
    good = ordered
    print(
        f"Buckets: New {len(rank(buckets['New'])[:MAX_NEW])}, "
        f"Signal {len(rank(buckets['Signal'])[:MAX_SIGNAL])}, "
        f"Evergreen {len(rank(buckets['Evergreen'])[:MAX_EVERGREEN])}",
        file=sys.stderr,
    )

    out = []
    out.append('<?xml version="1.0" encoding="UTF-8"?>')
    out.append('<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">')
    out.append("<channel>")
    out.append(f"<title>{escape(FEED_TITLE)}</title>")
    out.append(f"<link>{escape(FEED_LINK)}</link>")
    out.append(f"<description>{escape(FEED_DESC)}</description>")
    out.append(f"<language>en-ca</language>")
    out.append(f"<lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>")
    for it in good:
        bucket = it.get("_bucket", "New")
        age = it.get("_age", 0)
        cats = [it["platform"], it.get("format", "other"), bucket] + list(it.get("client_tags", []))
        verified = "verified" if it.get("verified") else "UNVERIFIED engagement"
        eng = it.get("engagement") or "engagement not verified"
        if bucket == "New":
            bucket_note = "New today."
        elif bucket == "Signal":
            bucket_note = f"Signal — still trending, day {age} since first seen."
        else:
            bucket_note = f"Evergreen — still trending, day {age} since first seen; expires after day 21."
        desc = (
            f"{bucket_note} {it.get('summary', '')} "
            f"Engagement: {eng} ({verified}). "
            f"Score: virality {it.get('virality', '?')}/5 + "
            f"growth {it.get('growth_rate', '?')}/5 + "
            f"sentiment {it.get('sentiment', '?')}/5 = {score(it)}/15."
        )
        if it.get("sound"):
            desc += f" Sound: {it['sound']}."
        out.append("<item>")
        out.append(f"<title>{escape(it['creator'] + ' — ' + it['title'])}</title>")
        out.append(f"<link>{escape(it['link'])}</link>")
        out.append(f"<guid isPermaLink=\"true\">{escape(it['link'])}</guid>")
        out.append(f"<pubDate>{to_rfc822(it['posted'])}</pubDate>")
        out.append(f"<description>{escape(desc)}</description>")
        for c in cats:
            out.append(f"<category>{escape(c)}</category>")
        out.append("</item>")
    out.append("</channel>")
    out.append("</rss>")

    with open(out_path, "w") as f:
        f.write("\n".join(out) + "\n")

    # Validate: must parse as XML, and must have <= 25 items.
    tree = ET.parse(out_path)
    n = len(tree.getroot().find("channel").findall("item"))
    assert n <= MAX_ITEMS, f"too many items: {n}"
    print(f"OK: {n} items -> {out_path}")


if __name__ == "__main__":
    main()
