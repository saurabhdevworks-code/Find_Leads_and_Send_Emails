#!/usr/bin/env python3
"""Discover publicly mapped businesses through OpenStreetMap / Overpass.

This intentionally does not scrape search-engine result pages or private websites.
OSM coverage is incomplete; absence of a result does not mean a business does not exist.
"""
import csv
import json
import html
import html.parser
import urllib.robotparser
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
    "verification_notes", "email_status", "email_source_url", "first_seen_at"
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
    # A bounding box is only a search optimization, never proof of district membership.
    params = urllib.parse.urlencode({
        "q": location, "format": "jsonv2", "limit": 1,
        "addressdetails": 1, "polygon_geojson": 1
    })
    results = fetch_json(NOMINATIM + "?" + params, timeout=30)
    if not results:
        raise RuntimeError(f"Could not locate '{location}' with OpenStreetMap Nominatim.")
    result = results[0]
    geometry = result.get("geojson")
    if not geometry:
        raise RuntimeError(
            f"Nominatim did not return a boundary polygon for '{location}'. "
            "Refusing to label nearby cities as leads in the requested district."
        )
    box = [float(v) for v in result["boundingbox"]]
    south, north, west, east = box
    return south, west, north, east, result.get("display_name", location), geometry

def point_in_ring(lon, lat, ring):
    inside = False
    if not ring or len(ring) < 4:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = float(ring[i][0]), float(ring[i][1])
        xj, yj = float(ring[j][0]), float(ring[j][1])
        if ((yi > lat) != (yj > lat)):
            cross = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-15) + xi
            if lon < cross:
                inside = not inside
        j = i
    return inside

def point_in_geometry(lon, lat, geometry):
    if not geometry or not isinstance(geometry, dict):
        return False
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    polygons = [coordinates] if kind == "Polygon" else coordinates if kind == "MultiPolygon" else []
    for polygon in polygons:
        if not polygon or not point_in_ring(lon, lat, polygon[0]):
            continue
        # GeoJSON rings after the first are holes.
        if not any(point_in_ring(lon, lat, hole) for hole in polygon[1:]):
            return True
    return False

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
      nwr["name"]["website"]({box});
      nwr["name"]["contact:website"]({box});
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


class PageParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.text_parts = []
    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.links.append(href)
    def handle_data(self, data):
        self.text_parts.append(data)

EMAIL_RE = re.compile(r"(?i)(?<![\w.+-])[\w.!#$%&'*+/=?^_{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
CONTACT_HINTS = ("contact", "about", "reach-us", "get-in-touch")

def fetch_page(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            return "", response.geturl()
        raw = response.read(1_500_000)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), response.geturl()

def public_email_from_website(website):
    """Read same-site public pages only when robots.txt permits.

    A redirect to a parked domain, directory, or unrelated host is not evidence
    for the business and must never supply its email address.
    """
    if not website:
        return "", ""
    parsed = urllib.parse.urlparse(website)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", ""
    original_host = parsed.netloc.lower().removeprefix("www.")
    base = f"{parsed.scheme}://{parsed.netloc}"
    robot = urllib.robotparser.RobotFileParser()
    robot.set_url(urllib.parse.urljoin(base, "/robots.txt"))
    try:
        robot.read()
    except Exception:
        return "", ""
    candidates = [website]
    try:
        homepage, final_url = fetch_page(website)
        final_host = urllib.parse.urlparse(final_url).netloc.lower().removeprefix("www.")
        if final_host != original_host:
            return "", ""
        parser = PageParser()
        parser.feed(homepage)
        for href in parser.links:
            absolute = urllib.parse.urljoin(final_url, href)
            if urllib.parse.urlparse(absolute).netloc.lower().removeprefix("www.") == original_host and any(h in urllib.parse.urlparse(absolute).path.lower() for h in CONTACT_HINTS):
                candidates.append(absolute)
    except Exception:
        pass
    candidates.extend(urllib.parse.urljoin(base, "/" + path) for path in ("contact", "contact-us", "about", "about-us"))
    checked = set()
    for page_url in candidates:
        normalized = page_url.split("#", 1)[0]
        if normalized in checked or urllib.parse.urlparse(normalized).netloc.lower().removeprefix("www.") != original_host:
            continue
        checked.add(normalized)
        try:
            if not robot.can_fetch(USER_AGENT, normalized):
                continue
            page, final_url = fetch_page(normalized)
            final_host = urllib.parse.urlparse(final_url).netloc.lower().removeprefix("www.")
            if final_host != original_host:
                continue
            matches = list(dict.fromkeys(normalize_email(x) for x in EMAIL_RE.findall(html.unescape(page)) if normalize_email(x)))
            if matches:
                # A Gmail/Outlook address is acceptable only when visibly published
                # on the business's own domain page; third-party redirects are rejected.
                return matches[0], final_url
        except Exception:
            continue
    return "", ""

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
        "email_source_url": source if email else "",
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
    south, west, north, east, display_location, boundary = locate_area(location)
    print(f"Using OpenStreetMap area: {display_location}")
    print("District boundary polygon loaded; candidates outside it will be rejected.")
    elements = query_overpass((south, west, north, east))
    print(f"OpenStreetMap returned {len(elements)} candidate map objects.")

    seen_at = datetime.now(timezone.utc).isoformat()
    records, seen_ids, seen_emails, seen_names = [], set(), set(), set()
    for element in elements:
        osm_id = f"{element.get('type')}-{element.get('id')}"
        if osm_id in seen_ids:
            continue
        seen_ids.add(osm_id)
        tags = element.get("tags", {})
        center = element.get("center", {})
        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))
        if lat is None or lon is None or not point_in_geometry(float(lon), float(lat), boundary):
            continue
        if not is_relevant(tags, industry):
            continue
        record = make_record(element, district, display_location, requested_fields, seen_at)
        # Prefer an email explicitly listed in OSM. Otherwise inspect the business's
        # own public website only when robots.txt permits. Never guess email patterns.
        if record and not record.get("email") and record.get("website"):
            discovered_email, evidence_url = public_email_from_website(record["website"])
            if discovered_email:
                record["email"] = discovered_email
                record["email_source_url"] = evidence_url
                record["email_status"] = "publicly_listed_on_website_format_only"
                record["verification_notes"] = "Email found on the business public website; mailbox deliverability is not verified."
            time.sleep(1.5)
        if record and record.get("email"):
            email_key = record["email"].strip().lower()
            name_key = re.sub(r"[^a-z0-9]+", "", record["business_name"].lower())
            if email_key not in seen_emails and name_key not in seen_names:
                records.append(record)
                seen_emails.add(email_key)
                seen_names.add(name_key)
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
        "qualified_leads_found": len(records),
        "required_email": True,
        "status": "SUCCESS" if len(records) == target else "INCOMPLETE",
        "incomplete_reason": "" if len(records) == target else f"Requested exactly {target} email-qualified leads, but only {len(records)} were found. No records without a public email were included.",
        "source": "OpenStreetMap candidates inside the Nominatim district polygon plus same-site robots.txt-permitted public business website pages",
        "generated_at": seen_at,
        "limitations": [
            "OpenStreetMap coverage is community-maintained and may be incomplete.",
            "A public map listing is not proof that a business is currently active.",
            "Only records with a publicly listed, syntactically valid email are included; email deliverability is not verified.",
            "Business websites are inspected only when robots.txt permits; blocked or disallowed pages are skipped.",
            "Candidates are checked against the returned district polygon; bounding-box-only matches are rejected.",
            "Emails from redirected third-party or parked-domain pages are rejected.",
            "Only businesses discovered in OpenStreetMap are considered; this is not a complete business directory.",
            "Custom fields not present in source data are left blank.",
            "No emails were sent and no lead data was committed to the public repository."
        ],
        "csv_file": str(csv_path)
    }
    Path("artifacts/run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if len(records) != target:
        raise SystemExit(2)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Discovery failed: {exc}", file=sys.stderr)
        raise
