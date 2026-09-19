# Car Finder

Finds used cars for sale on Craigslist and shows how their price falls with mileage, so a buyer can tell a fair price from a bad one.

## Searching

**Search**:
One question put to Craigslist: a state, a city, a make, a model, and which Owner types to include.
_Avoid_: Query, scrape

**Listing**:
One car for sale on Craigslist, with its price, mileage, photos, and Owner type.
_Avoid_: Car, post, posting, result

**Owner type**:
Who is selling a Listing: a private owner or a dealer.
_Avoid_: Seller type, purveyor

**Listing source**:
Where Listings come from for a Search: Craigslist's search results.
_Avoid_: Scraper, crawler

**Listing details**:
The extra attributes a Listing's own page carries (transmission, condition, paint, title status), fetched only when asked for.
_Avoid_: Attributes, specs

## Pricing

**Price curve**:
The fitted line of price against mileage for one Owner type in a Search.
_Avoid_: Trend line, fit, regression

## The page

**Search page**:
The one page where a person runs a Search and reads the chart of its Listings.
_Avoid_: Dashboard, app

**Preview**:
The Listing shown in the panel beside the chart while the pointer is over its point. It never covers the chart.
_Avoid_: Tooltip, hover card

**Pinned Listing**:
The Listing a person clicked. It stays in the panel when nothing is being previewed, and its Listing details are loaded.
_Avoid_: Selected listing, active listing
