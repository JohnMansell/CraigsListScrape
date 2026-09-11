# Craigslist search: pagination, rate limits, image hotlinking

Research for issue #2, run 2026-09-11 from one IP. Tools: curl and httpx with a desktop Chrome User-Agent, and headless Chrome 153 through Selenium for the network capture and the image test. Craigslist can change any of this without notice; the JSON API below is undocumented.

## Answers

1. **Pagination:** the static search page is not the full result set, and it has no paging parameter. The page's own JavaScript reads results from a JSON API at `sapi.craigslist.org`, which gives the total count, every result in batches, and more fields than the static page (post id, mileage, posted time).
2. **Rate limits:** 150 detail pages in three runs of 50 (1 s delay, no delay, 5 at once) all returned 200 with full content. No block was seen, so what a block looks like is still unknown. Recommended pacing: one request at a time with a 0.5 s delay, and stop the run on the first non-200 response or page without a post id.
3. **Image hotlinking:** works. `images.craigslist.org` images load in an `<img>` tag on a page served from localhost.

## 1. Pagination

### City URLs now redirect

`https://<city>.craigslist.org/search/cta?...` returns 301 to `https://www.craigslist.org/search/area/<city>?...&cat=cta`. The redirect keeps search parameters but drops `s=120`, `s=360` and `page=2`, so the static page has no paging.

### The static page is incomplete

| Search (owner listings) | `li.cl-static-search-result` | JSON-LD items | API `totalResultCount` |
| --- | --- | --- | --- |
| Los Angeles, all cars | 353 | 345 | 3655 |
| Los Angeles, toyota | 337 | 330 | 477 |
| Los Angeles, honda civic | 63 | 62 | 69 |
| Orange County, honda civic | 29 | 29 | 30 |

SF Bay, all cars, owner and dealer: 359 static, 337 JSON-LD (API not fetched). The static page is capped near 360 and also misses a few listings on small searches; the cause of the small-search gap was not determined.

### JSON-LD skips listings with no photos

The JSON-LD list (`script#ld_searchpage_results`) is not the same length as the static list, so pairing the two by position gives wrong prices and images. On the Los Angeles all-cars page, the 8 static titles missing from JSON-LD are exactly the 8 API items with no image list, and their detail pages have no photos (0 `images.craigslist.org/<code>_` references, 0 `<img>` tags; a listing with photos had 52 and 11). The first mismatch was at index 10.

### The JSON API

Captured from headless Chrome loading `https://www.craigslist.org/search/area/losangeles?cat=cta&purveyor=owner` and scrolling. The page made these requests, and each one also works from plain curl with no cookies, User-Agent, Origin or Referer:

1. `https://sapi.craigslist.org/web/v8/postings/search/full?batch=0-0-360-0-0&cat=cta&purveyor=owner&searchPath=area%2Flosangeles&lang=en&cc=us`
   Returns `data.totalResultCount` (3655), `data.cacheTs`, `data.decode.minPostingId`, `data.decode.minPostedDate`, and the first 360 results in `data.items`. Search filters go in as the same query parameters as the page, for example `auto_make_model=honda%20civic`.
2. `.../postings/search/full?batch=0-<cacheTs>-0-1-0&<same search params>`
   Returns `data.cacheId`, `data.maxPostedTs`, and all 3655 results in a short form (id, posted time, price, geo only). 243 KB.
3. `https://sapi.craigslist.org/web/v8/postings/search/batch?batch=0-<offset>-1080-1-0-<maxPostedTs>-<cacheTs>&cacheId=<cacheId>&lang=en&cc=us`
   Returns `data.minPostingId` and up to 1080 full results in `data.batch`. The browser asked for offsets 0, 1080, 2160 and 3240. A wrong `maxPostedTs` gives 400 with `"That url is unsupported (bad max_posting_ts)"`.

Result formats. Tagged fields are `[tag, value]` pairs:

- `full` item: `[postIdOffset, postedOffset, 145, price, "n:m~lat~lon", imageSuffix, [13, token], [4, "3:<imageCode>", ...], [6, slug], [9, odometer], [10, "$2,900"], title]`
- `batch` item: `[postIdOffset, title, ["3:<imageCode>", ...], [6, slug], [13, token], [9, odometer], [10, "$25,000"]]`

Checked against live detail pages:

| Field | How to read it | Checked on |
| --- | --- | --- |
| Post id | `minPostingId + postIdOffset` | 7964841675 (`full`), 7963865802 (`batch`) |
| Listing URL | `https://www.craigslist.org/view/d/<slug>/<token>` | both listings above loaded |
| Mileage | tag 9, a plain integer | 167000 is "odometer: 167,000"; 59144 is "odometer: 59,144" |
| Image URL | drop the `3:`, append `_600x450.jpg` (also `_300x300.jpg`, `_50x50c.jpg`) | all three sizes returned 200 `image/jpeg` |
| Geo | lat and lon in the `n:m~lat~lon` string | matched the JSON-LD geo for the same listing |

Not checked: `postedOffset + minPostedDate` for the newest listing equals `maxPostedTs`, so it is most likely the posted Unix time. Field 145 and the other `batch=` numbers are unexplained. Tag 9 was missing on 1 of 360 and 1 of 1080 results (unknown mileage), and tag 4 was missing for listings with no photos.

## 2. Rate limits

Script: httpx `AsyncClient`, redirects followed, desktop Chrome User-Agent, 50 detail page URLs per run taken from different parts of the Los Angeles all-cars static page. Each page was checked for status, `post id: <digits>`, `attrgroup`, a `Retry-After` header, and the words captcha, blocked, unusual activity, too many requests, access denied, rate limit.

| Run | Delay | At once | Wall time | Statuses | Pages with post id | Median / max per fetch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 s | 1 | 51.7 s | 50 x 200 | 50 | 25 ms / 148 ms |
| 2 | 0 | 1 | 1.8 s | 50 x 200 | 50 | 36 ms / 109 ms |
| 3 | 0 | 5 | 0.4 s | 50 x 200 | 50 | 37 ms / 107 ms |

About 30 more requests (search pages, API calls, detail spot checks) went out in the same half hour. No run showed block words or `Retry-After`. Testing stopped there rather than risk blocking the IP, so a block's status code and page are not known.

**Recommendation for detail page fetches:** one at a time, 0.5 s delay between requests (about 2 pages per second, 50 pages in under 30 s). That is 4 to 10 times slower than the runs that passed. Treat any non-200 status, or a 200 page with no post id, as a possible block: log it and stop fetching for the rest of that search instead of retrying. With the JSON API, detail pages are only needed for extra attributes (VIN, fuel, transmission), since post id and mileage come with the search results.

## 3. Image hotlinking

- curl on `https://images.craigslist.org/00808_gDKihemAvUu_0Cz0t2_600x450.jpg`: 200 `image/jpeg`, 45421 bytes, both with no Referer and with `Referer: http://localhost:8080/` plus `Origin: http://localhost:8080`. No `Cross-Origin-Resource-Policy` or `Access-Control-*` headers. `Cache-control: public, max-age=2592000`.
- Headless Chrome loading `http://localhost:<port>/index.html` with three `<img>` tags pointing at `images.craigslist.org`: all three decoded (598x450, 337x450, 300x225).

Not tested: what an image URL returns after its listing is deleted.

## What this changes for open tickets

- #3: pairing the static list with JSON-LD by position is wrong whenever a listing has no photos, and the static list is incomplete. Follow-up #11 covers reading results from the JSON API instead.
- #4: post id and mileage are in the API results, so detail pages are only needed for the other attributes. Use the pacing above.
- #9: hotlinking works, so the page does not need to download images.
