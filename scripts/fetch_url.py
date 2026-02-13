"""
FeedFwd — URL Content Extractor
================================
Fetches a URL and extracts the main article text, stripping navigation,
ads, sidebars, and other boilerplate.

What it does:
  1. Fetches the page with httpx (handles redirects, timeouts)
  2. Parses HTML with BeautifulSoup
  3. Extracts the main content using a priority-based strategy:
     - First looks for <article> tags (most blogs/news sites use this)
     - Then tries <main> tags
     - Then looks for common content class names (post-content, entry-content, etc.)
     - Falls back to <body> and strips obvious non-content elements
  4. Cleans up whitespace and returns plain text

Why a separate script:
  URL fetching is reused by both the /learn command and the distiller.
  Keeping it isolated makes it easy to test and improve extraction
  logic independently.

Usage:
  python fetch_url.py <url>
  # Prints extracted text to stdout
"""

import re
import sys

import httpx
from bs4 import BeautifulSoup, Tag


# Elements that never contain article content — we strip these first
# to reduce noise before looking for the main content.
NOISE_TAGS = [
    "script", "style", "nav", "header", "footer", "aside",
    "iframe", "noscript", "svg", "form", "button",
]

# CSS class/id patterns that typically indicate non-content sections.
# We use these as a heuristic — not perfect, but catches most cases.
NOISE_PATTERNS = re.compile(
    r"(sidebar|widget|comment|share|social|related|recommend|"
    r"newsletter|subscribe|advertisement|promo|popup|modal|"
    r"cookie|consent|banner|menu|breadcrumb)",
    re.IGNORECASE,
)

# CSS class/id patterns that typically indicate main content.
# We try these before falling back to just grabbing <body>.
CONTENT_PATTERNS = re.compile(
    r"(article|post|entry|content|story|blog|prose|text|body-text|"
    r"main-content|page-content|post-content|entry-content|"
    r"article-content|article-body|post-body)",
    re.IGNORECASE,
)

# Browser-like User-Agent so sites don't block us as a bot.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def fetch_and_extract(url: str) -> str:
    """Fetch a URL and extract the main article text.

    Strategy (in priority order):
      1. Look for <article> tags — most reliable signal
      2. Look for <main> tags
      3. Look for divs with content-related class names
      4. Fall back to <body> with noise stripped

    Args:
        url: The URL to fetch.

    Returns:
        Cleaned article text as a string.

    Raises:
        httpx.HTTPStatusError: If the server returns 4xx/5xx.
        httpx.ConnectError: If the URL can't be reached.
    """
    # Fetch the page. We follow redirects and set a reasonable timeout.
    # The timeout has two parts: connect (how long to establish connection)
    # and read (how long to wait for the response body).
    response = httpx.get(
        url,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
    )
    response.raise_for_status()

    # Parse HTML
    soup = BeautifulSoup(response.text, "html.parser")

    # Step 1: Remove noise elements (scripts, nav, footer, etc.)
    _strip_noise(soup)

    # Step 2: Try to find the main content using our priority strategy
    content = (
        _try_tag(soup, "article")
        or _try_tag(soup, "main")
        or _try_content_class(soup)
        or _fallback_body(soup)
    )

    if not content:
        return ""

    # Step 3: Clean up the text
    return _clean_text(content)


def _strip_noise(soup: BeautifulSoup) -> None:
    """Remove elements that never contain article content.

    Modifies the soup in-place. We do this before searching for
    content so noise doesn't pollute our results.
    """
    # Remove noise tags entirely
    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove elements with noise-related class/id names.
    # We check tag.attrs is not None because decomposing a parent tag
    # detaches its children, leaving them with attrs=None. If we
    # encounter one of those orphaned children later in the loop,
    # we skip it.
    for tag in soup.find_all(True):
        if tag.attrs is None:
            continue
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        if NOISE_PATTERNS.search(classes) or NOISE_PATTERNS.search(tag_id):
            tag.decompose()


def _try_tag(soup: BeautifulSoup, tag_name: str) -> str | None:
    """Try to extract content from a specific HTML tag.

    If multiple tags are found (e.g., multiple <article> tags on a
    page), we pick the one with the most text content — that's
    usually the main article, not a sidebar teaser.
    """
    tags = soup.find_all(tag_name)
    if not tags:
        return None

    # Pick the tag with the most text
    best = max(tags, key=lambda t: len(t.get_text()))
    text = best.get_text()

    # Only accept if there's meaningful content (not just a wrapper)
    if len(text.strip()) > 200:
        return text

    return None


def _try_content_class(soup: BeautifulSoup) -> str | None:
    """Try to find content by CSS class/id name patterns.

    Many sites use classes like "post-content", "entry-content",
    "article-body", etc. We look for divs matching these patterns.
    """
    candidates = []

    for tag in soup.find_all(["div", "section"]):
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        if CONTENT_PATTERNS.search(classes) or CONTENT_PATTERNS.search(tag_id):
            text = tag.get_text()
            if len(text.strip()) > 200:
                candidates.append(text)

    if candidates:
        # Return the longest match (most likely the full article)
        return max(candidates, key=len)

    return None


def _fallback_body(soup: BeautifulSoup) -> str | None:
    """Last resort: grab text from <body> after noise removal.

    Since we already stripped noise elements in _strip_noise(),
    what's left in <body> should be mostly content. Not perfect,
    but better than nothing.
    """
    body = soup.find("body")
    if body:
        text = body.get_text()
        if len(text.strip()) > 200:
            return text
    return None


def _clean_text(raw_text: str) -> str:
    """Clean up extracted text for the distiller.

    - Collapses multiple blank lines into single ones
    - Strips leading/trailing whitespace from each line
    - Removes lines that are just whitespace
    - Caps output at ~10,000 words (the distiller doesn't need more)
    """
    lines = raw_text.split("\n")

    # Strip each line and remove pure-whitespace lines
    cleaned = []
    prev_blank = False
    for line in lines:
        line = line.strip()
        if not line:
            if not prev_blank:
                cleaned.append("")
                prev_blank = True
        else:
            cleaned.append(line)
            prev_blank = False

    text = "\n".join(cleaned).strip()

    # Cap at ~10,000 words to avoid sending enormous content
    # to the distiller. Most articles are 1,000-3,000 words.
    words = text.split()
    if len(words) > 10_000:
        text = " ".join(words[:10_000]) + "\n\n[Content truncated at 10,000 words]"

    return text


def main():
    if len(sys.argv) < 2:
        print("Usage: python fetch_url.py <url>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    try:
        text = fetch_and_extract(url)
        print(text)
    except httpx.HTTPStatusError as e:
        print(f"HTTP error fetching {url}: {e.response.status_code}", file=sys.stderr)
        sys.exit(1)
    except httpx.ConnectError:
        print(f"Could not connect to {url}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
