# Iran International EPG

XMLTV programme guide for Iran International, scraped hourly from the official
schedule page by GitHub Actions and committed back to this repository.

## Feed

```
https://raw.githubusercontent.com/<username>/<repo>/main/output/iranintl.xml
```

Channel id: `iranintl.iitv`

Add the URL as an XMLTV source in m3u-editor, Dispatcharr, Threadfin, Jellyfin,
Tvheadend or any other XMLTV client, then map it to your Iran International
channel using the `iranintl.iitv` tvg-id.

## Running locally

```
pip install -r requirements.txt
python generate.py
```

Run from the repository root; output is written to `output/iranintl.xml`.

## Notes

The schedule is parsed from a JSON payload embedded in the page markup, as there
is no public API. If the site changes structure the run fails loudly and leaves
the previous feed in place rather than publishing an empty guide.

## License

MIT, see `LICENSE`. This covers the code only, not the schedule data itself.
