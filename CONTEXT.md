# Car Finder

Finds used cars for sale on Craigslist and shows how their price falls with mileage, so a buyer can tell a fair price from a bad one.

## Searching

**Search**:
One question put to Craigslist: a state, a city, a make, a model, and which Owner types and Sources to include.
_Avoid_: Query, scrape

**Listing**:
One car for sale, with its price, mileage, model year, photos, Owner type, and Source. Craigslist has no year field, so a Craigslist Listing's year is read from its title, and is unknown when the title has none.
_Avoid_: Car, post, posting, result

**Owner type**:
Who is selling a Listing: a private owner or a dealer.
_Avoid_: Seller type, purveyor

**Source**:
The website a Listing was found on: Craigslist, Carfax or CarMax. A Search can include any of them. Carfax and CarMax have dealers only (CarMax sells its own cars), and the same car can appear once per Source.
_Avoid_: Listing source, scraper, crawler

**Listing details**:
The extra attributes a Craigslist Listing's own page carries (transmission, condition, paint, title status), fetched only when asked for. A Carfax Listing has no separate Listing details: its Search result already carries everything Preview shows (dealer, owners, accidents, a price-drop note). A CarMax Listing is the same: store name and city, an on-sale date, a price-drop note, and "one owner" only when known, with no accidents line; its page is never fetched.
_Avoid_: Attributes, specs

## Pricing

**Price curve**:
The fitted line of price against mileage for one Owner type from one Source in a Search. Craigslist has one per Owner type; Carfax and CarMax have one each.
_Avoid_: Trend line, fit, regression

## The page

**Display filter**:
A rule, such as "one owner", that fades the Listings failing it to light-grey dots on the chart. It never removes a Listing from a Price curve, so filtering never makes a curve less accurate.
_Avoid_: Search filter, query filter

**Search page**:
The one page where a person runs a Search and reads the chart of its Listings.
_Avoid_: Dashboard, app

**Preview**:
The Listing shown in the panel beside the chart while the pointer is over its point. It never covers the chart.
_Avoid_: Tooltip, hover card

**Pinned Listing**:
The Listing a person clicked. It stays in the panel when nothing is being previewed. Its Listing details are loaded for a Craigslist Listing; a Carfax or CarMax Listing needs no load, its Search result already has them.
_Avoid_: Selected listing, active listing
