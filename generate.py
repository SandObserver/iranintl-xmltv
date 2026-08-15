import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import Element, SubElement, indent, tostring

import requests

SCHEDULE_URL = "https://www.iranintl.com/tvschedule"
OUTPUT_PATH = os.path.join("output", "iranintl.xml")

CHANNEL_ID = "iranintl.iitv"
CHANNEL_NAME_FA = "ایران اینترنشنال"
CHANNEL_NAME_EN = "Iran International"
CHANNEL_ICON = "https://www.iranintl.com/images/ii/ii-logo-fa.svg"
CHANNEL_LANG = "fa"

GENERATOR_NAME = "iranintl-epg"
REQUEST_TIMEOUT = 30
MIN_PROGRAMMES = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fa,en;q=0.9",
}


class ScrapeError(RuntimeError):
    pass


def fetch_page(url=SCHEDULE_URL):
    response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def extract_schedule_data(html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"([\s\S]*?)"\]\)', html)
    if not chunks:
        raise ScrapeError("No Next.js flight payload found; page structure has changed")

    combined = "".join(chunks)
    key_match = re.search(r'\\"scheduleData\\":\s*(\[)', combined)
    if not key_match:
        raise ScrapeError("scheduleData key not found in flight payload")

    start = key_match.start(1)
    depth = 0
    index = start
    raw = None
    while index < len(combined):
        char = combined[index]
        if char == "\\":
            index += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                raw = combined[start : index + 1]
                break
        index += 1

    if raw is None:
        raise ScrapeError("Unterminated scheduleData array in flight payload")

    unescaped = raw.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")
    try:
        data = json.loads(unescaped)
    except json.JSONDecodeError as exc:
        raise ScrapeError(f"scheduleData is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ScrapeError("scheduleData is not a list of days")
    return data


def parse_duration_minutes(value):
    parts = str(value or "").split(":")
    if len(parts) < 2:
        return 0
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 0


def parse_start(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_programmes(schedule_days):
    programmes = []
    skipped = 0

    for day in schedule_days:
        if not isinstance(day, dict):
            continue
        for item in day.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            start = parse_start(item.get("broadcastTime"))
            if start is None:
                skipped += 1
                continue

            details = item.get("programme") or {}
            title = (details.get("title") or details.get("englishTitle") or "").strip()
            if not title:
                skipped += 1
                continue

            minutes = parse_duration_minutes(item.get("duration"))
            if minutes <= 0:
                skipped += 1
                continue

            programmes.append(
                {
                    "start": start,
                    "stop": start + timedelta(minutes=minutes),
                    "title": title,
                    "category": (details.get("type") or "").strip(),
                    "slug": (details.get("slug") or "").strip(),
                }
            )

    if skipped:
        print(f"Skipped {skipped} unusable schedule entries", file=sys.stderr)

    return normalise(programmes)


def normalise(programmes):
    programmes.sort(key=lambda item: (item["start"], item["stop"]))

    result = []
    for programme in programmes:
        if result and programme["start"] == result[-1]["start"]:
            continue
        if result and programme["start"] < result[-1]["stop"]:
            result[-1]["stop"] = programme["start"]
        if programme["stop"] <= programme["start"]:
            continue
        result.append(programme)

    return [item for item in result if item["stop"] > item["start"]]


def format_timestamp(value):
    return value.strftime("%Y%m%d%H%M%S %z")


def build_xml(programmes):
    tv = Element(
        "tv",
        attrib={
            "generator-info-name": GENERATOR_NAME,
            "generator-info-url": SCHEDULE_URL,
        },
    )

    channel = SubElement(tv, "channel", id=CHANNEL_ID)
    SubElement(channel, "display-name", lang=CHANNEL_LANG).text = CHANNEL_NAME_FA
    SubElement(channel, "display-name", lang="en").text = CHANNEL_NAME_EN
    SubElement(channel, "icon", src=CHANNEL_ICON)

    for programme in programmes:
        element = SubElement(
            tv,
            "programme",
            start=format_timestamp(programme["start"]),
            stop=format_timestamp(programme["stop"]),
            channel=CHANNEL_ID,
        )
        SubElement(element, "title", lang=CHANNEL_LANG).text = programme["title"]
        if programme["category"]:
            SubElement(element, "category", lang="en").text = programme["category"]
        if programme["slug"]:
            SubElement(element, "url").text = (
                f"https://www.iranintl.com/vod/{programme['slug']}"
            )

    indent(tv, space="  ")
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(tv, encoding="utf-8")


def write_output(payload, path=OUTPUT_PATH):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


def main():
    programmes = build_programmes(extract_schedule_data(fetch_page()))

    if len(programmes) < MIN_PROGRAMMES:
        raise ScrapeError(
            f"Only {len(programmes)} programmes parsed, expected at least "
            f"{MIN_PROGRAMMES}; refusing to overwrite the existing feed"
        )

    write_output(build_xml(programmes))
    print(
        f"Wrote {len(programmes)} programmes to {OUTPUT_PATH} "
        f"({format_timestamp(programmes[0]['start'])} to "
        f"{format_timestamp(programmes[-1]['stop'])})"
    )


if __name__ == "__main__":
    try:
        main()
    except (ScrapeError, requests.RequestException) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
