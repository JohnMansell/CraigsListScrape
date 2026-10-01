"""PROTOTYPE, throwaway. Question: can the app get Carfax listings as easily as Craigslist's?

Run: uv run python prototypes/carfax_probe.py --zip 94103 --make Honda --model Civic

Findings (2026-09-29), from probing by hand:
- www.carfax.com search pages sit behind DataDome (403 "Please enable JS"), but the
  JSON API those pages call, helix.carfax.com/search/v2/vehicles, answers plain httpx.
- Search is by zip + radius (miles), not by city. make/model are Carfax's names.
- rows is capped at 25 and page at 50, so one search sees at most 1250 listings.
  priceMin/priceMax filter server-side, so price bands would get past the cap.
- Dealers only: every listing has a dealer. No private sellers, so no "owner" curve.
- Every listing seen had price and mileage; the id is a string (VIN + dealer + date).
"""
import argparse
import time

import httpx

API = "https://helix.carfax.com/search/v2/vehicles"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
ROWS = 25
MAX_PAGE = 50


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", default="94103")
    parser.add_argument("--radius", type=int, default=50)
    parser.add_argument("--make", default="Honda")
    parser.add_argument("--model", default="Civic")
    parser.add_argument("--pages", type=int, default=3, help="stop after this many pages")
    args = parser.parse_args()

    # --- Page Through The API

    listings = []
    total = pages = None
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        page = 1
        while page <= min(args.pages, MAX_PAGE) and (pages is None or page <= pages):
            params = {"zip": args.zip, "radius": args.radius, "make": args.make,
                      "model": args.model, "vehicleCondition": "USED", "rows": ROWS, "page": page}
            response = client.get(API, params=params)
            response.raise_for_status()
            data = response.json()
            total, pages = data["totalListingCount"], data["totalPageCount"]
            listings += data["listings"]
            print(f"page {page}/{pages}: {len(data['listings'])} listings, total {total}")
            page += 1
            time.sleep(0.5)

    # --- Map To The App's Listing Fields

    print(f"\n{len(listings)} of {total} listings fetched; the API serves at most {ROWS * MAX_PAGE}\n")
    for item in listings[:15]:
        dealer = item.get("dealer", {})
        print(f"{item['currentPrice']:>7,}  {item.get('mileage', '?'):>7,} mi  "
              f"{item['year']} {item['make']} {item['model']} {item.get('trim', '')}  "
              f"| {dealer.get('name')} ({dealer.get('city')}, {dealer.get('state')})  "
              f"| first seen {item.get('firstSeen')}  | {item['vdpUrl']}")
    missing = {key: sum(key not in item for item in listings)
               for key in ("currentPrice", "mileage", "firstSeen", "images", "dealer")}
    print(f"\nmissing fields across all fetched: {missing}")


if __name__ == "__main__":
    main()
