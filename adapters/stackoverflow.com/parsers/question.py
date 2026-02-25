"""
Custom parser for Stack Overflow question pages.

A question page contains:
- The question itself (title, body, votes, author, tags)
- Multiple answers (body, votes, author, accepted status)

This parser extracts both and returns them as a flat list
where type="question" or type="answer".
"""

from html.parser import HTMLParser
import re


def _strip_html(html: str) -> str:
    """Remove HTML tags, decode entities, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse(status_code: int, headers: dict, body: str, args: dict) -> list[dict]:
    """
    Parse a Stack Overflow question page.

    Returns list of records: first record is the question,
    followed by answers sorted by votes (descending).
    """
    # We use basic string matching + regex here rather than a full HTML parser
    # because we need specific elements from a complex page.
    # In production, this would use selectolax or BeautifulSoup.

    records = []

    # --- Extract question ---
    title_match = re.search(r'<h1[^>]*itemprop="name"[^>]*>.*?<a[^>]*>(.+?)</a>', body, re.DOTALL)
    title = _strip_html(title_match.group(1)) if title_match else "Unknown"

    q_votes_match = re.search(r'itemprop="upvoteCount"[^>]*>(\d+)', body)
    q_votes = int(q_votes_match.group(1)) if q_votes_match else 0

    q_body_match = re.search(
        r'<div[^>]*class="s-prose js-post-body"[^>]*itemprop="text"[^>]*>(.*?)</div>',
        body, re.DOTALL
    )
    q_body = _strip_html(q_body_match.group(1))[:500] if q_body_match else ""

    q_author_match = re.search(
        r'itemprop="author"[^>]*>.*?itemprop="name"[^>]*>([^<]+)',
        body, re.DOTALL
    )
    q_author = q_author_match.group(1).strip() if q_author_match else "Unknown"

    records.append({
        "type": "question",
        "title": title,
        "votes": q_votes,
        "author": q_author,
        "body": q_body,
    })

    # --- Extract answers ---
    # Each answer lives in a <div id="answer-XXXXX">
    answer_blocks = re.findall(
        r'<div[^>]*id="answer-(\d+)"[^>]*>(.*?)</div>\s*</div>\s*</div>',
        body, re.DOTALL
    )

    for answer_id, answer_html in answer_blocks:
        a_votes_match = re.search(r'data-value="(-?\d+)"', answer_html)
        a_votes = int(a_votes_match.group(1)) if a_votes_match else 0

        a_body_match = re.search(
            r'<div[^>]*class="s-prose js-post-body"[^>]*>(.*?)</div>',
            answer_html, re.DOTALL
        )
        a_body = _strip_html(a_body_match.group(1))[:500] if a_body_match else ""

        a_author_match = re.search(
            r'itemprop="name"[^>]*>([^<]+)', answer_html
        )
        a_author = a_author_match.group(1).strip() if a_author_match else "Unknown"

        is_accepted = 'itemprop="acceptedAnswer"' in answer_html

        records.append({
            "type": "✓ answer" if is_accepted else "answer",
            "title": "",
            "votes": a_votes,
            "author": a_author,
            "body": a_body,
        })

    # Sort answers by votes (question always first)
    question = records[0]
    answers = sorted(records[1:], key=lambda x: x["votes"], reverse=True)

    return [question] + answers
