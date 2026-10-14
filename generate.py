import html
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element, SubElement, indent, tostring

SCHEDULE_URL = "https://www.iranintl.com/tvschedule"
OUTPUT_PATH = Path("output") / "iranintl.xml"

CHANNEL_ID = "iranintl.iitv"
CHANNEL_NAME_FA = "ایران اینترنشنال"
CHANNEL_NAME_EN = "Iran International"
CHANNEL_ICON = "https://www.iranintl.com/images/ii/ii-logo-en.svg"
CHANNEL_LANG = "fa"
CHANNEL_LANGUAGE_NAME = "فارسی"
CHANNEL_URL = "https://www.iranintl.com/live"

GENERATOR_NAME = "iranintl-epg"
REQUEST_TIMEOUT = 30
DETAILS_TIMEOUT = 15
MIN_PROGRAMMES = 10

PROGRAMME_PAGE = "https://www.iranintl.com/fa/program/{slug}"
ICON_HOST = "i.iranintl.com"
DESC_MAX_CHARS = 400
# Bulletins have no show page on the site; every named show has one.
BULLETIN_CATEGORY = "News"
SHOW_CATEGORY = "Talk"
DOCUMENTARY_CATEGORY = "Documentary"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa,en;q=0.9",
}

type Fetcher = Callable[[str, float], str]


class ScrapeError(RuntimeError):
    pass


@dataclass
class Programme:
    start: datetime
    stop: datetime
    title: str
    category: str = ""
    slug: str = ""
    icon: str = ""
    desc: str = ""


@dataclass(frozen=True)
class Details:
    icon: str = ""
    desc: str = ""


@dataclass
class Summary:
    programmes: list[Programme] = field(default_factory=list)
    icons: int = 0
    descs: int = 0


def fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: bytes = response.read()
        return body.decode(response.headers.get_content_charset() or "utf-8")


def extract_schedule_data(page: str) -> list[Any]:
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"([\s\S]*?)"\]\)', page)
    if not chunks:
        raise ScrapeError("No Next.js flight payload found; page structure has changed")

    combined = "".join(chunks)
    key_match = re.search(r'\\"scheduleData\\":\s*(\[)', combined)
    if not key_match:
        raise ScrapeError("scheduleData key not found in flight payload")

    raw = _bracketed(combined, key_match.start(1))
    unescaped = raw.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
    try:
        data = json.loads(unescaped)
    except json.JSONDecodeError as exc:
        raise ScrapeError(f"scheduleData is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ScrapeError("scheduleData is not a list of days")
    return data


def _bracketed(text: str, start: int) -> str:
    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
        index += 1
    raise ScrapeError("Unterminated scheduleData array in flight payload")


def parse_duration_minutes(value: object) -> int:
    parts = str(value or "").split(":")
    if len(parts) < 2:
        return 0
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 0


def parse_start(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_programmes(schedule_days: list[Any]) -> list[Programme]:
    programmes: list[Programme] = []
    skipped = 0
    for day in schedule_days:
        if not isinstance(day, dict):
            continue
        for item in day.get("items") or []:
            if not isinstance(item, dict):
                continue
            programme = _programme(item)
            if programme is None:
                skipped += 1
            else:
                programmes.append(programme)

    if skipped:
        print(f"Skipped {skipped} unusable schedule entries", file=sys.stderr)
    return normalise(programmes)


def _programme(item: dict[str, Any]) -> Programme | None:
    start = parse_start(item.get("broadcastTime"))
    details = item.get("programme") or {}
    title = str(details.get("title") or details.get("englishTitle") or "").strip()
    minutes = parse_duration_minutes(item.get("duration"))
    if start is None or not title or minutes <= 0:
        return None
    slug = str(details.get("slug") or "").strip()
    return Programme(
        start=start,
        stop=start + timedelta(minutes=minutes),
        title=title,
        category=category_for(slug, str(details.get("englishTitle") or "")),
        slug=slug,
    )


def category_for(slug: str, english_title: str) -> str:
    if not slug:
        return BULLETIN_CATEGORY
    if "documentary" in english_title.casefold():
        return DOCUMENTARY_CATEGORY
    return SHOW_CATEGORY


def normalise(programmes: list[Programme]) -> list[Programme]:
    programmes = sorted(programmes, key=lambda item: (item.start, item.stop))
    result: list[Programme] = []
    for programme in programmes:
        if result and programme.start == result[-1].start:
            continue
        if result and programme.start < result[-1].stop:
            result[-1].stop = programme.start
        result.append(programme)
    return result


def programme_details(slug: str, fetcher: Fetcher = fetch) -> Details:
    try:
        page = fetcher(PROGRAMME_PAGE.format(slug=slug), DETAILS_TIMEOUT)
    except OSError:
        return Details()
    return Details(icon=find_icon(page), desc=find_desc(page))


def find_icon(page: str) -> str:
    match = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page)
    if not match:
        return ""
    url = html.unescape(match.group(1))
    if not url.startswith(f"https://{ICON_HOST}/"):
        return ""
    return url.split("?", 1)[0]


def find_desc(page: str) -> str:
    match = re.search(r'<meta[^>]+name="description"[^>]+content="([^"]*)"', page)
    if not match:
        return ""
    return " ".join(html.unescape(match.group(1)).split())[:DESC_MAX_CHARS]


def attach_details(programmes: list[Programme], fetcher: Fetcher = fetch) -> tuple[int, int]:
    slugs = sorted({item.slug for item in programmes if item.slug})
    details = {slug: programme_details(slug, fetcher) for slug in slugs}
    for item in programmes:
        found = details.get(item.slug, Details())
        item.icon = found.icon
        item.desc = found.desc
    icons = sum(1 for found in details.values() if found.icon)
    descs = sum(1 for found in details.values() if found.desc)
    return icons, descs


def format_timestamp(value: datetime) -> str:
    return value.strftime("%Y%m%d%H%M%S %z")


def build_xml(programmes: list[Programme]) -> bytes:
    tv = Element("tv", {"generator-info-name": GENERATOR_NAME, "generator-info-url": SCHEDULE_URL})

    channel = SubElement(tv, "channel", id=CHANNEL_ID)
    SubElement(channel, "display-name", lang=CHANNEL_LANG).text = CHANNEL_NAME_FA
    SubElement(channel, "display-name", lang="en").text = CHANNEL_NAME_EN
    SubElement(channel, "icon", src=CHANNEL_ICON)
    SubElement(channel, "url").text = CHANNEL_URL

    for programme in programmes:
        element = SubElement(
            tv,
            "programme",
            start=format_timestamp(programme.start),
            stop=format_timestamp(programme.stop),
            channel=CHANNEL_ID,
        )
        SubElement(element, "title", lang=CHANNEL_LANG).text = programme.title
        if programme.desc:
            SubElement(element, "desc", lang=CHANNEL_LANG).text = programme.desc
        if programme.category:
            SubElement(element, "category", lang="en").text = programme.category
        SubElement(element, "language", lang=CHANNEL_LANG).text = CHANNEL_LANGUAGE_NAME
        if programme.icon:
            SubElement(element, "icon", src=programme.icon)
        if programme.slug:
            SubElement(element, "url").text = PROGRAMME_PAGE.format(slug=programme.slug)

    indent(tv, space="  ")
    data: bytes = tostring(tv, encoding="utf-8", xml_declaration=True)
    return data


def generate(fetcher: Fetcher = fetch) -> Summary:
    programmes = build_programmes(extract_schedule_data(fetcher(SCHEDULE_URL, REQUEST_TIMEOUT)))
    if len(programmes) < MIN_PROGRAMMES:
        raise ScrapeError(
            f"Only {len(programmes)} programmes parsed, expected at least {MIN_PROGRAMMES}; "
            "refusing to overwrite the existing feed"
        )
    icons, descs = attach_details(programmes, fetcher)
    return Summary(programmes, icons, descs)


def write_output(payload: bytes, path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(payload)
    partial.replace(path)


def main(fetcher: Fetcher = fetch, output: Path = OUTPUT_PATH) -> int:
    try:
        summary = generate(fetcher)
    except (ScrapeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    programmes = summary.programmes
    write_output(build_xml(programmes), output)
    print(
        f"Wrote {len(programmes)} programmes to {output} "
        f"({format_timestamp(programmes[0].start)} to {format_timestamp(programmes[-1].stop)}); "
        f"resolved {summary.icons} icons and {summary.descs} descriptions"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
