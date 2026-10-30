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
by posted date (newest first). Output is capped at MAX_ITEMS (25).

Nothing here scrapes, posts, contacts a creator, or buys anything. Collection
is a separate step; this script only normalizes, ranks, caps and validates.
"""
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

MAX_ITEMS = 25
MIN_CANDIDATES = 100
FEED_TITLE = "Daily Social Trends"
FEED_LINK = "https://atgabelotto.github.io/trends-feed/"  # GitHub Pages URL once enabled
FEED_DESC = (
    "Daily raw social trends across Instagram, TikTok and Pinterest, "
    "whittled from 100+ candidates to 25 by virality, growth rate and sentiment. "
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

    good.sort(key=lambda it: (-score(it), it["posted"]), reverse=False)
    # sort above is by -score then posted ascending; re-sort posted desc within ties
    good.sort(key=lambda it: it["posted"], reverse=True)
    good.sort(key=lambda it: -score(it))
    good = good[:MAX_ITEMS]

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
        cats = [it["platform"], it.get("format", "other")] + list(it.get("client_tags", []))
        verified = "verified" if it.get("verified") else "UNVERIFIED engagement"
        eng = it.get("engagement") or "engagement not verified"
        desc = (
            f"{it.get('summary', '')} "
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
