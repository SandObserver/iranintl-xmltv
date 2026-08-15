# Iran International EPG

XMLTV programme guide for Iran International, generated hourly from the
official schedule page by GitHub Actions and committed back to this repository.

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

The schedule is read from a JSON payload embedded in the page markup, as there is
no public API. If the site changes structure the run fails loudly and leaves the
previous feed in place rather than publishing an empty guide.

Programme artwork is referenced by URL from Iran International's own servers. No
images are downloaded or stored in this repository.

## Attribution

This is an unofficial, non-commercial project and is not affiliated with,
endorsed by, or connected to Iran International or Volant Media. Programme
titles, descriptions, artwork, schedule information, and trademarks remain the
property of their respective owners and are referenced here for the sole purpose
of identifying the broadcast they describe.

## License

MIT, see `LICENSE`. This covers the code in this repository only. It does not
cover the schedule data, descriptions, or artwork.
