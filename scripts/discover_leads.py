#!/usr/bin/env python3
"""Discover publicly mapped businesses through OpenStreetMap / Overpass.

This intentionally does not scrape search-engine result pages or private websites.
OSM coverage is incomplete; absence of a result does not mean a business does not exist.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
USER_AGENT = "UPBusinessLeadResearch/1.0 (GitHub Actions; contact: repository maintainer)"
BASE_FIELDS = [
    "lead_id", "business_name", "location", "district", "services",
    "mobile", "email", "website", "source_url", "verification_status",
    "verification_notes", "email_status", "first_seen_at"
]
INDUSTRY_TERMS = [
    "digital marketing", "marketing", "advertising", "seo", "social media",
    "branding", "web design", "web development", "creative agency",
    "media agency", "internet marketing", "digital agency", "public relations",
    "content marketing", "online marketing"
]
ALIASES = {
    "business_name": ("business_name", "name", "company_name"),
    "name": ("business_name", "name", "company_name"),
    "company_name": ("business_name", "name", "company_name"),
    "location": ("location", "address"),
    "district": ("district",),
    "services": ("services", "service", "industry"),
    "mobile": ("mobile", "phone", "telephone"),
    "phone": ("mobile", "phone", "telephone"),
    "email": ("email",),
    "website": ("website", "url"),
    "url": ("website", "url"),
    "source_url": ("source_url", "source"),
    "source": ("source_url", "source"),
    "verification_status": ("verification_status",),
    "verification_notes": ("verification_notes",),
    "email_status": ("email_status",),
    "first_seen_at": ("first_seen_at",),
}

def fetch_json(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def locate_area(location):
    params = urllib.parse.urlencode({"q": location, "format": "jsonv2", "limit": 1, "addressdetails": 1})
    results = fetch_json(NOMINATIM + "?" + params, timeout=30)
    if not results:
        raise RuntimeError(f"Could not locate '{location}' with OpenStreetMap Nominatim.")
    box = [float(v) for v in results[0]["boundingbox"]]
    south, north, west, east = box
    return south, west, north, east, results[0].get("display_name", location)

def query_overpass(bbox):
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    query = f"""
    [out:json][timeout:40];
    (
      nwr["name"]["office"~"advertising|marketing|company|consulting|it",i]({box});
      nwr["name"]["craft"~"advertising|marketing",i]({box});
      nwr["name"]["advertising"]({box});
      nwr["name"]["description"~"marketing|advertising|digital agency|SEO|social media",i]({box});
    );
    out center tags;
    """
    last_error = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            url = endpoint + "?" + urllib.parse.urlencode({"data": query})
            return fetch_json(url, timeout=75).get("elements", [])
        except Exception as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")

def tags_text(tags):
    keys = ("name", "description", "office", "craft", "advertising", "industry", "brand", "operator")
    return " ".join(str(tags.get(k, "")) for k in keys).lower()

def is_relevant(tags, industry):
    text = tags_text(tags)
    requested = [x.strip().lower() for x in re.split(r"[,;/]", industry) if len(x.strip()) > 2]
    terms = list(dict.fromkeys(INDUSTRY_TERMS + requested))
    # Require an industry signal rather than treating every generic company as a lead.
    return any(term in text for term in terms)

def first(tags, *keys):
    for key in keys:
        value = tags.get(key)
        if value:
            return str(value).strip()
    return ""

def address_from(tags, fallback):
    parts = [
        first(tags, "addr:housenumber"), first(tags, "addr:street"),
        first(tags, "addr:suburb", "addr:neighbourhood"),
        first(tags, "addr:city", "addr:town", "addr:village"),
        first(tags, "addr:postcode")
    ]
    return ", ".join(x for x in parts if x) or fallback

def element_url(element):
    return f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}"

def normalize_website(value):
    if not value:
        return ""
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    if not re.match(r"^https?://", value, re.I):
        return "https://" + value
    return value

def normalize_email(value):
    value = value.strip().lower()
    return value if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) else ""

def make_record(element, district, display_location, requested_fields, seen_at):
    tags = element.get("tags", {})
    name = first(tags, "name", "official_name", "brand")
    if not name:
        return None
    center = element.get("center", {})
    lat = element.get("lat", center.get("lat"))
    lon = element.get("lon", center.get("lon"))
    fallback = display_location
    address = address_from(tags, fallback)
    phone = first(tags, "contact:phone", "phone", "contact:mobile", "mobile")
    email = normalize_email(first(tags, "contact:email", "email"))
    website = normalize_website(first(tags, "contact:website", "website", "contact:url", "url"))
    services = first(tags, "description", "office", "craft", "advertising", "industry")
    source = element_url(element)
    record = {
        "lead_id": f"osm-{element.get('type')}-{element.get('id')}",
        "business_name": name,
        "location": address,
        "district": district,
        "services": services,
        "mobile": phone,
        "email": email,
        "website": website,
        "source_url": source,
        "verification_status": "public_source_found_contact_unverified",
        "verification_notes": "Business record and contact fields are from OpenStreetMap tags; independently confirm before outreach.",
        "email_status": "format_only_not_deliverability_checked" if email else "not_listed",
        "first_seen_at": seen_at,
        "latitude": lat if lat is not None else "",
        "longitude": lon if lon is not None else "",
    }
    for field in requested_fields:
        key = field.strip().lower()
        if key in record:
            record[field] = record[key]
        elif key in ALIASES:
            record[field] = record.get(ALIASES[key][0], "")
        else:
            # Unknown/custom fields remain blank; never invent values.
            record[field] = ""
    return record

def main():
    request_path = Path("config/search-request.json")
    if not request_path.exists():
        raise SystemExit("config/search-request.json not found. Run Configure Lead Search first.")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    industry = str(request.get("industry", "")).strip()
    location = str(request.get("location", "")).strip()
    district = str(request.get("district", "")).strip() or location
    target = int(request.get("lead_count", 25))
    if not industry or not location or target < 1 or target > 100:
        raise SystemExit("Invalid search request: industry/location required; lead_count must be 1-100.")

    requested_fields = request.get("custom_fields", [])
    if not isinstance(requested_fields, list):
        requested_fields = []
    requested_fields = [str(x).strip() for x in requested_fields if str(x).strip()]
    headers = list(dict.fromkeys(BASE_FIELDS + requested_fields + ["latitude", "longitude"]))
    print(f"Locating search area: {location}")
    south, west, north, east, display_location = locate_area(location)
    print(f"Using OpenStreetMap area: {display_location}")
    elements = query_overpass((south, west, north, east))
    print(f"OpenStreetMap returned {len(elements)} candidate map objects.")

    seen_at = datetime.now(timezone.utc).isoformat()
    records, seen_ids = [], set()
    for element in elements:
        osm_id = f"{element.get('type')}-{element.get('id')}"
        if osm_id in seen_ids:
            continue
        seen_ids.add(osm_id)
        tags = element.get("tags", {})
        if not is_relevant(tags, industry):
            continue
        record = make_record(element, district, display_location, requested_fields, seen_at)
        if record:
            records.append(record)
        if len(records) >= target:
            break

    Path("artifacts").mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = Path("artifacts") / f"leads-{stamp}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    summary = {
        "industry": industry, "location": location, "district": district,
        "requested_lead_count": target, "leads_found": len(records),
        "source": "OpenStreetMap via Nominatim and Overpass",
        "generated_at": seen_at,
        "limitations": [
            "OpenStreetMap coverage is community-maintained and may be incomplete.",
            "A public map listing is not proof that a business is currently active.",
            "Contact details are not independently deliverability-verified.",
            "Custom fields not present in source data are left blank.",
            "No emails were sent and no lead data was committed to the public repository."
        ],
        "csv_file": str(csv_path)
    }
    Path("artifacts/run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        raise
