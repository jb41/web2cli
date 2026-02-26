"""
Custom parser for HN HTML story listing pages.

Used by saved, upvoted, and submissions pages which return
HTML rather than JSON. HN structure: paired rows — tr.athing
(title/url/rank) + next sibling tr (score/author/comments/age).
"""

import re

from selectolax.parser import HTMLParser


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """Parse an HN HTML page listing stories (saved, upvoted, submissions)."""
    tree = HTMLParser(body)
    records = []

    for row in tree.css("tr.athing"):
        record = _parse_story_row(row)
        if record:
            records.append(record)

    return records


def _parse_story_row(row) -> dict | None:
    """Extract a story from a tr.athing and its next sibling."""
    # --- Main row: rank, title, URL ---
    rank_el = row.css_first("span.rank")
    rank = _parse_int(rank_el.text(strip=True).rstrip(".")) if rank_el else 0

    title_el = row.css_first("span.titleline > a")
    if title_el is None:
        return None
    title = title_el.text(strip=True)
    url = title_el.attributes.get("href", "")

    item_id = row.attributes.get("id", "")

    # Make relative URLs absolute
    if url and not url.startswith("http"):
        url = f"https://news.ycombinator.com/{url}"

    hn_url = f"https://news.ycombinator.com/item?id={item_id}" if item_id else ""

    # --- Subtext row (next sibling): score, author, comments, age ---
    subtext = row.next
    # Skip whitespace text nodes
    while subtext and not hasattr(subtext, "css_first"):
        subtext = subtext.next
    if subtext:
        # Walk one more if this isn't the subtext row
        sub_el = subtext.css_first("td.subtext") or subtext.css_first("span.subline")
        if sub_el is None and subtext.next:
            subtext = subtext.next
            while subtext and not hasattr(subtext, "css_first"):
                subtext = subtext.next

    score = 0
    author = ""
    comments = 0
    age = ""

    if subtext and hasattr(subtext, "css_first"):
        score_el = subtext.css_first("span.score")
        if score_el:
            score = _parse_int(score_el.text(strip=True).split()[0])

        author_el = subtext.css_first("a.hnuser")
        if author_el:
            author = author_el.text(strip=True)

        age_el = subtext.css_first("span.age")
        if age_el:
            age = age_el.text(strip=True)

        # Comments: last <a> in subline that contains a number + "comment"
        for link in reversed(subtext.css("a")):
            text = link.text(strip=True)
            if "comment" in text or "discuss" in text:
                m = re.match(r"(\d+)", text)
                comments = int(m.group(1)) if m else 0
                break

    return {
        "rank": rank,
        "title": title,
        "score": score,
        "author": author,
        "comments": comments,
        "age": age,
        "url": url,
        "id": item_id,
        "hn_url": hn_url,
    }


def _parse_int(text: str) -> int:
    text = text.strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        return 0
