import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import generate
from generate import Programme, ScrapeError

START = datetime(2026, 1, 5, 18, 0, tzinfo=UTC)


def item(offset_minutes: int, title: str = "Show", duration: str = "00:30:00", **details: str) -> dict[str, Any]:
    moment = START + timedelta(minutes=offset_minutes)
    return {
        "broadcastTime": moment.isoformat().replace("+00:00", "Z"),
        "duration": duration,
        "programme": {"title": title, "type": "programme", **details},
    }


def page(days: list[Any]) -> str:
    payload = json.dumps({"scheduleData": days})
    escaped = payload.replace("\\", "\\\\").replace('"', '\\"')
    half = len(escaped) // 2
    return (
        f'<script>self.__next_f.push([1,"{escaped[:half]}"])</script>'
        f'<script>self.__next_f.push([1,"{escaped[half:]}"])</script>'
    )


def show_page(icon: str, desc: str) -> str:
    return f'<meta property="og:image" content="{icon}"/><meta name="description" content="{desc}"/>'


def fake_fetcher(pages: dict[str, str]) -> generate.Fetcher:
    def fetch(url: str, timeout: float) -> str:
        if url not in pages:
            raise OSError(f"no page for {url}")
        return pages[url]

    return fetch


def test_extract_schedule_data_reads_split_payload() -> None:
    days = [{"items": [item(0, title='Quote "here" and \\ slash')]}]
    assert generate.extract_schedule_data(page(days)) == days


@pytest.mark.parametrize(
    ("html", "message"),
    [
        ("<html></html>", "No Next.js flight payload"),
        ('self.__next_f.push([1,"nothing"])', "scheduleData key not found"),
        ('self.__next_f.push([1,"{\\"scheduleData\\":[1,2"])', "Unterminated"),
        ('self.__next_f.push([1,"{\\"scheduleData\\":[1,}]"])', "not valid JSON"),
    ],
)
def test_extract_schedule_data_rejects_bad_pages(html: str, message: str) -> None:
    with pytest.raises(ScrapeError, match=message):
        generate.extract_schedule_data(html)


def test_extract_schedule_data_rejects_non_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(json, "loads", lambda _: {"days": []})
    with pytest.raises(ScrapeError, match="not a list"):
        generate.extract_schedule_data(page([]))


@pytest.mark.parametrize(
    ("value", "minutes"),
    [("01:15:00", 75), ("00:30", 30), ("90", 0), ("aa:bb", 0), (None, 0)],
)
def test_parse_duration_minutes(value: object, minutes: int) -> None:
    assert generate.parse_duration_minutes(value) == minutes


def test_parse_start() -> None:
    assert generate.parse_start("2026-01-05T18:00:00Z") == START
    assert generate.parse_start("2026-01-05T21:30:00+03:30") == START
    assert generate.parse_start("2026-01-05T18:00:00") == START
    assert generate.parse_start("") is None
    assert generate.parse_start("tomorrow") is None


def test_build_programmes_skips_unusable_entries(capsys: pytest.CaptureFixture[str]) -> None:
    days: list[Any] = [
        "not a day",
        {"items": [item(0), "not an item", item(30, title=""), item(60, duration="00:00"), {"duration": "00:30"}]},
        {"items": None},
    ]
    programmes = generate.build_programmes(days)
    assert [p.title for p in programmes] == ["Show"]
    assert "Skipped 3 unusable" in capsys.readouterr().err


def test_build_programmes_labels_bulletins_shows_and_documentaries() -> None:
    days = [
        {
            "items": [
                item(0, englishTitle="IITV News"),
                item(30, slug=" talk ", englishTitle="News Special with Host"),
                item(60, slug="doc", englishTitle="Amnesty Report Documentary Series"),
            ]
        }
    ]
    bulletin, show, documentary = generate.build_programmes(days)
    assert (bulletin.category, bulletin.slug) == ("News", "")
    assert (show.category, show.slug) == ("Talk", "talk")
    assert documentary.category == "Documentary"


def test_build_programmes_falls_back_to_english_title() -> None:
    entry = item(0)
    entry["programme"] = {"englishTitle": "News"}
    assert generate.build_programmes([{"items": [entry]}])[0].title == "News"


def test_normalise_removes_duplicates_and_overlaps_and_keeps_gaps() -> None:
    programmes = [
        Programme(START + timedelta(minutes=20), START + timedelta(minutes=50), "B"),
        Programme(START, START + timedelta(minutes=30), "A"),
        Programme(START, START + timedelta(minutes=10), "A again"),
        Programme(START + timedelta(hours=2), START + timedelta(hours=3), "C"),
    ]
    result = generate.normalise(programmes)
    assert [(p.title, p.stop - START) for p in result] == [
        ("A again", timedelta(minutes=10)),
        ("B", timedelta(minutes=50)),
        ("C", timedelta(hours=3)),
    ]


def test_find_icon_accepts_only_site_images_and_keeps_them_as_published() -> None:
    icon = generate.find_icon(show_page("https://i.iranintl.com/a.jpg?w=10&amp;h=5", ""))
    assert icon == "https://i.iranintl.com/a.jpg"
    assert generate.find_icon(show_page("https://www.iranintl.com/images/ii/opengraph-image.webp", "")) == ""
    assert generate.find_icon("<html></html>") == ""


def test_find_desc_collapses_whitespace_and_truncates() -> None:
    assert generate.find_desc(show_page("", "Talk &amp; \n analysis")) == "Talk & analysis"
    assert len(generate.find_desc(show_page("", "x" * 1000))) == generate.DESC_MAX_CHARS
    assert generate.find_desc("<html></html>") == ""


def test_attach_details_only_sets_found_icons() -> None:
    programmes = [
        Programme(START, START + timedelta(minutes=30), "A", slug="a"),
        Programme(START + timedelta(minutes=30), START + timedelta(hours=1), "B", slug="b"),
        Programme(START + timedelta(hours=1), START + timedelta(hours=2), "C"),
    ]
    pages = {generate.PROGRAMME_PAGE.format(slug="a"): show_page("https://i.iranintl.com/a.jpg", "About A")}
    assert generate.attach_details(programmes, fake_fetcher(pages)) == (1, 1)
    assert programmes[0].icon == "https://i.iranintl.com/a.jpg"
    assert programmes[0].desc == "About A"
    assert programmes[1].icon == programmes[1].desc == ""
    assert programmes[2].icon == ""


def test_build_xml_leaves_out_empty_fields() -> None:
    programmes = [
        Programme(
            START, START + timedelta(minutes=30), "A", category="Documentary", slug="a", icon="https://i/x", desc="D"
        ),
        Programme(START + timedelta(hours=1), START + timedelta(hours=2), "B"),
    ]
    root = ET.fromstring(generate.build_xml(programmes))
    channel = root.find("channel")
    assert channel is not None
    assert channel.get("id") == generate.CHANNEL_ID
    full, bare = root.findall("programme")
    assert full.get("start") == "20260105180000 +0000"
    assert [child.tag for child in full] == ["title", "desc", "category", "language", "icon", "url"]
    assert [child.tag for child in bare] == ["title", "language"]


def test_generate_refuses_short_schedules() -> None:
    pages = {generate.SCHEDULE_URL: page([{"items": [item(0)]}])}
    with pytest.raises(ScrapeError, match="Only 1 programmes"):
        generate.generate(fake_fetcher(pages))


def test_main_writes_feed(tmp_path: Path) -> None:
    pages = {
        generate.SCHEDULE_URL: page([{"items": [item(minutes * 30, slug="a") for minutes in range(12)]}]),
        generate.PROGRAMME_PAGE.format(slug="a"): show_page("https://i.iranintl.com/a.jpg", "About A"),
    }
    output = tmp_path / "out" / "feed.xml"
    assert generate.main(fake_fetcher(pages), output) == 0
    assert len(ET.parse(output).getroot().findall("programme")) == 12


def test_main_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert generate.main(fake_fetcher({}), tmp_path / "feed.xml") == 1
    assert "error: no page for" in capsys.readouterr().err
