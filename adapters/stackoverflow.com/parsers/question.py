"""
Custom parser for Stack Overflow question pages.

A question page contains:
- The question itself (title, body, votes, author, tags)
- Multiple answers (body, votes, author, accepted status)

This parser extracts both and returns them as a flat list
where type="question" or type="answer".
"""

from selectolax.parser import HTMLParser


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """
    Parse a Stack Overflow question page.

    Returns list of records: first record is the question,
    followed by answers sorted by votes (descending).
    """
    tree = HTMLParser(body)
    records = []

    # --- Extract question ---
    title_el = tree.css_first("#question-header h1 a")
    title = title_el.text(strip=True) if title_el else "Unknown"

    q_votes_el = tree.css_first("#question .js-vote-count")
    q_votes = _parse_int(q_votes_el.text(strip=True)) if q_votes_el else 0

    q_body_el = tree.css_first("#question .s-prose.js-post-body")
    q_body = q_body_el.text(strip=True)[:500] if q_body_el else ""

    q_author_el = tree.css_first("#question .post-signature:last-child .user-details a")
    q_author = q_author_el.text(strip=True) if q_author_el else "Unknown"

    q_tags = [t.text(strip=True) for t in tree.css("#question .post-tag")]

    records.append({
        "type": "question",
        "title": title,
        "votes": q_votes,
        "author": q_author,
        "tags": ", ".join(q_tags),
        "body": q_body,
    })

    # --- Extract answers ---
    for answer_el in tree.css("#answers .answer"):
        a_votes_el = answer_el.css_first(".js-vote-count")
        a_votes = _parse_int(a_votes_el.text(strip=True)) if a_votes_el else 0

        a_body_el = answer_el.css_first(".s-prose.js-post-body")
        a_body = a_body_el.text(strip=True)[:500] if a_body_el else ""

        a_author_el = answer_el.css_first(".post-signature:last-child .user-details a")
        a_author = a_author_el.text(strip=True) if a_author_el else "Unknown"

        is_accepted = "js-accepted-answer" in (answer_el.attributes.get("class", "") or "")

        records.append({
            "type": "\u2713 answer" if is_accepted else "answer",
            "title": "",
            "votes": a_votes,
            "author": a_author,
            "tags": "",
            "body": a_body,
        })

    # Sort answers by votes (question always first)
    question = records[0]
    answers = sorted(records[1:], key=lambda x: x["votes"], reverse=True)

    return [question] + answers


def _parse_int(text: str) -> int:
    """Parse vote count text like '13126' or '13k'."""
    text = text.strip().lower().replace(",", "")
    if text.endswith("k"):
        return int(float(text[:-1]) * 1000)
    if text.endswith("m"):
        return int(float(text[:-1]) * 1000000)
    try:
        return int(text)
    except ValueError:
        return 0
