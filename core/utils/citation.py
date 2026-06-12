from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        if not parsed.scheme:
            return f"https://{url.lstrip('/')}"
        return url
    except Exception:
        return url


def short_citation(country: str, jurisdiction: str, title: str, year: int | None) -> str:
    parts = [country]
    if jurisdiction and jurisdiction != country:
        parts.append(jurisdiction)
    parts.append(title)
    if year:
        parts.append(f"({year})")
    return " | ".join(parts)
