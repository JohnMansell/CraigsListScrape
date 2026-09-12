# Craigslist search: pagination, rate limits, image hotlinking

Research for issue #2, run 2026-09-11 from one IP. Tools: curl and httpx with a desktop Chrome User-Agent, and headless Chrome 153 through Selenium for the network capture and the image test. Craigslist can change any of this without notice; the JSON API below is undocumented.

## Answers

1. **Pagination:** the 36 results seen on 2026-09-10 were not a page size, since the static page lists up to about 360. Whether they were complete can't be checked now: the same search today shows 29 static and 30 in the API. The static page is not a reliable full result set, and it has no paging parameter. The page's own JavaScript reads results from a JSON API at `sapi.craigslist.org`, which gives the total count, every result in batches, and more fields than the static page (post id, mileage, posted time).
2. **Rate limits:** 150 detail pages in three runs of 50 (1 s delay, no delay, 5 at once) all returned 200 with full content. No block was seen, so what a block looks like is still unknown. Recommended pacing: one request at a time with a 0.5 s delay, stopping on a possible block (details in section 2).
3. **Image hotlinking:** works. `images.craigslist.org` images load in an `<img>` tag on a page served from localhost.

## 1. Pagination

### City URLs now redirect

`https://<city>.craigslist.org/search/cta?...` returns 301 to `https://www.craigslist.org/search/area/<city>?...&cat=cta`. The redirect keeps search parameters but drops `s=120` and `page=2` (both 301 to the plain search URL), so the static page has no paging.

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
   Returns `data.cacheId`, `data.maxPostedTs`, and all 3655 results in a short form, `[postIdOffset, postedOffset, 145, price, geo, imageSuffix]` sometimes followed by an extra integer, with no title, slug, token or mileage. 243 KB.
3. `https://sapi.craigslist.org/web/v8/postings/search/batch?batch=0-<offset>-1080-1-0-<maxPostedTs>-<cacheTs>&cacheId=<cacheId>&lang=en&cc=us`
   Returns `data.minPostingId` and up to 1080 full results in `data.batch`. The browser asked for offsets 0, 1080, 2160 and 3240. A wrong `maxPostedTs` gives 400 with `"That url is unsupported (bad max_posting_ts)"`.

Result formats. Tagged fields are `[tag, value]` pairs; tags seen are 4 image codes, 6 slug, 9 odometer, 10 price text, 13 token:

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

`postedOffset + minPostedDate` is the posted Unix time, and field 145 and the `n:m` geo prefix are both decoded in section 4. The other `batch=` numbers are still unexplained, and the strings are not free-form: invented values give 400. Layouts vary, so read fields by tag and from the ends of the list, not by fixed position:

- `full` items (22 of 360 differ): with no photos, `imageSuffix` is `0` and tag 4 is missing (8 items); an extra negative integer such as `-6` can follow `imageSuffix` (14 items). The title is always the last element.
- `batch` items: the image list is always third but can be empty (27 of 1080).
- Tag 9 (mileage) was missing on 1 of 360 and 1 of 1080 results, and tag 10 (price) on 2 of 1080.

## 2. Rate limits

Script: httpx `AsyncClient`, redirects followed, desktop Chrome User-Agent, 50 detail page URLs per run taken from different parts of the Los Angeles all-cars static page. Each page was checked for status, `post id: <digits>`, `attrgroup`, a `Retry-After` header, and the words captcha, blocked, unusual activity, too many requests, access denied, rate limit.

| Run | Delay | At once | Wall time | Statuses | Pages with post id | Median / max per fetch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 s | 1 | 51.7 s | 50 x 200 | 50 | 25 ms / 148 ms |
| 2 | 0 | 1 | 1.8 s | 50 x 200 | 50 | 36 ms / 109 ms |
| 3 | 0 | 5 | 0.4 s | 50 x 200 | 50 | 37 ms / 107 ms |

About 30 more requests (search pages, API calls, detail spot checks) went out in the same half hour. No run showed block words or `Retry-After`. Testing stopped there rather than risk blocking the IP, so a block's status code and page are not known.

**Recommendation for detail page fetches:** one at a time, 0.5 s delay between requests (about 2 pages per second, 50 pages in under 30 s). That sits between run 1 (about 1 page per second) and run 2 (about 28 pages per second), both of which passed. Treat any non-200 status, or a 200 page with no post id, as a possible block: log it and stop fetching detail pages for the rest of that Search instead of retrying. With the JSON API, detail pages are only needed for extra attributes (VIN, fuel, transmission), since post id and mileage come with the search results.

## 3. Image hotlinking

- curl on `https://images.craigslist.org/00808_gDKihemAvUu_0Cz0t2_600x450.jpg`: 200 `image/jpeg`, 45421 bytes, both with no Referer and with `Referer: http://localhost:8080/` plus `Origin: http://localhost:8080`. No `Cross-Origin-Resource-Policy` or `Access-Control-*` headers. `Cache-control: public, max-age=2592000`.
- Headless Chrome loading `http://localhost:<port>/index.html` with three `<img>` tags pointing at `images.craigslist.org`: all three decoded (598x450, 337x450, 300x225).

Not tested: what an image URL returns after its listing is deleted.

## 4. Decoding the API (2026-09-11, grilling session on #11)

Checked live from one IP, mostly against `cat=cta&auto_make_model=honda civic&searchPath=area/orangecounty`.

### `purveyor`

| Value | Result |
| --- | --- |
| `purveyor=owner` | owner listings only |
| `purveyor=dealer` | dealer listings only |
| omitted | both, merged |
| `purveyor=all` | identical to omitting it |
| passed twice | the first value wins, silently |

### Field 145 is the purveyor code

Index 2 of a `full` item is **145 for owner, 146 for dealer**. Confirmed on Los Angeles, SF Bay, and Orange County, filtered and unfiltered. A merged response carries both values mixed (Orange County: 159 owner, 201 dealer).

`batch` items have no purveyor code: the only bare integer in one is the post id offset. So results past 360 cannot be labelled and a merged request cannot be sorted afterwards. Run one search per owner type instead.

### The geo prefix

In `"n:m~lat~lon"`, `n` indexes `data.decode.locations` and `m` indexes `data.decode.locationDescriptions`.

- `locations` entries are `[siteId, citySlug]` or `[siteId, citySlug, subareaSlug]`, for example `[103, "orangecounty"]` and `[7, "losangeles", "sfv"]`.
- `locationDescriptions` is the seller-typed location text, typos included: "Highgrove", "West Covina", "foutain valley". Correct on 6 of 6 checked.

`batch` items have no geo at all, so location is knowable for the first 360 results only.

### `totalResultCount` counts local results only

Orange County / honda civic / dealer reports `totalResultCount` 15 but returns 60 distinct post ids, 59 of whose titles contain "Civic". The 15 are exactly the results located in `orangecounty`; the other 45 are syndicated from elsewhere:

| Location | Results |
| --- | --- |
| orangecounty | 15 |
| losangeles (6 subareas) | 27 |
| inlandempire | 13 |
| sandiego/nsd | 2 |
| modesto | 2 |
| phoenix/cph | 1 |

The merged response returned exactly those 15 dealer items, set for set. Owner searches showed no such bleed: 31 of 31 local here, and 360 of 360 within Los Angeles subareas on LA all-cars.

**So `totalResultCount` cannot drive paging.** Page until a batch comes back short or empty. On dealer searches, a tally above the reported total is normal, not drift.

No server-side fix was found. `search_distance=25&postal=92868` returned *more* out-of-area results (74) and moved the total to 74; `searchDistance` gave `total=1`; `vicinity=0` changed nothing; `searchPath=orangecounty` without the `area/` prefix returns no `decode` block.

### Other confirmations

- Post id: `data.decode.minPostingId + postIdOffset` in `full`, `data.minPostingId + postIdOffset` in `batch`.
- Price: the bare integer at index 3 of a `full` item matched tag 10 on 31 of 31 results.
- Posted time: `postedOffset + data.decode.minPostedDate` resolved to a plausible current timestamp, so it is the posted Unix time.
- Images: 4 to 23 codes per listing, and a code can repeat within one listing.
- Unfiltered dealer totals are large and sane: Los Angeles 4896, SF Bay 12216, Orange County 1949.

## What this changes for open tickets

- **#3** rewritten around the JSON API, with #11 folded into it and closed: one search per owner type, paging that never trusts `totalResultCount`, no location field, deduplicated image codes, loud failure on a response-shape change, and fixtures-only tests.
- **#4** rescoped to an on-demand attribute fetch for a single listing, outside the Search path, since post id and mileage now arrive with search results. Use the pacing in section 2.
- **#7** closed. The cache existed to avoid refetching detail pages, and there are none in the Search path.
- **#8** now blocked by #3, #5, and #6, with progress reported once per API request.
- **#9**: hotlinking works, so the Search page does not need to download images. Out-of-area dealer listings appear in every dealer search and are kept deliberately.
