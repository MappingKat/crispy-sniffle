"""
Boulder Permit Site Check: data quality check.

Runs a set of rule-based QA checks against a point layer and writes:
  - a CSV of every issue found (one row per record per failed check)
  - optionally, a GeoJSON of flagged features to publish as a dashboard layer

The source can be a local GeoJSON file or an ArcGIS feature service layer URL
(e.g. .../FeatureServer/0). Rules live in a JSON config so the same script
works on the open-data permits layer and on the Field Maps collection layer.

Standard library only, so it runs in ArcGIS Pro's Python or any Python 3.9+.

Usage:
  python qa_check.py --config qa_config_permits.json --out qa_report.csv
  python qa_check.py --config qa_config_permits.json --source https://.../FeatureServer/0 \
      --out qa_report.csv --geojson-out qa_flags.geojson
"""

import argparse
import csv
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y")


# ---------------------------------------------------------------- loading

def load_geojson_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["features"]


def load_feature_service(layer_url, token=None, page_size=1000):
    """Page through a feature service layer and return GeoJSON features in WGS84."""
    features, offset = [], 0
    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "outSR": 4326,
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        if token:
            params["token"] = token
        url = layer_url.rstrip("/") + "/query?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.load(resp)
        if "error" in data:
            raise RuntimeError(f"Service error: {data['error']}")
        batch = data.get("features", [])
        features.extend(batch)
        if len(batch) < page_size and not data.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(batch)
    return features


def load_boundary(path):
    """Return a list of polygon rings (outer rings only) from a GeoJSON file."""
    rings = []
    for feat in load_geojson_file(path):
        geom = feat.get("geometry") or {}
        if geom.get("type") == "Polygon":
            rings.append(geom["coordinates"][0])
        elif geom.get("type") == "MultiPolygon":
            rings.extend(poly[0] for poly in geom["coordinates"])
    return rings


# ---------------------------------------------------------------- helpers

def parse_date(value):
    """Accept ISO strings, common US format, or epoch milliseconds (ArcGIS)."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).replace(tzinfo=None)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return "unparseable"


def is_blank(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def point_in_ring(x, y, ring):
    """Ray-casting point-in-polygon test."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------- checks

def run_checks(features, cfg, boundary_rings=None, today=None):
    today = today or datetime.now()
    id_field = cfg["id_field"]
    issues = []

    def flag(feat, check, severity, field, value, message):
        props = feat.get("properties") or {}
        issues.append({
            "record_id": props.get(id_field, "<no id>"),
            "check": check,
            "severity": severity,
            "field": field,
            "value": "" if value is None else value,
            "message": message,
        })

    # Duplicate IDs and stacked points need a pass over the whole layer first.
    id_counts = Counter((f.get("properties") or {}).get(id_field) for f in features)
    coord_counts = Counter()
    for f in features:
        geom = f.get("geometry")
        if geom and geom.get("type") == "Point":
            coord_counts[tuple(round(c, 6) for c in geom["coordinates"][:2])] += 1

    bbox = cfg.get("bbox")  # [min_lon, min_lat, max_lon, max_lat]

    for feat in features:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")

        # Geometry
        if not geom or not geom.get("coordinates"):
            flag(feat, "missing_geometry", "error", "SHAPE", None, "Record has no location")
        elif geom.get("type") == "Point":
            x, y = geom["coordinates"][:2]
            if boundary_rings is not None:
                if not any(point_in_ring(x, y, r) for r in boundary_rings):
                    flag(feat, "outside_boundary", "error", "SHAPE", f"{x:.5f},{y:.5f}",
                         "Point falls outside the city boundary")
            elif bbox and not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]):
                flag(feat, "outside_boundary", "error", "SHAPE", f"{x:.5f},{y:.5f}",
                     "Point falls outside the Boulder bounding box")
            if coord_counts[(round(x, 6), round(y, 6))] > 1:
                flag(feat, "stacked_point", "warning", "SHAPE", f"{x:.5f},{y:.5f}",
                     "Another record shares this exact location")

        # IDs
        rid = props.get(id_field)
        if is_blank(rid):
            flag(feat, "missing_id", "error", id_field, None, "Record has no ID")
        elif id_counts[rid] > 1:
            flag(feat, "duplicate_id", "error", id_field, rid,
                 f"ID appears {id_counts[rid]} times")

        # Required fields
        for field in cfg.get("required_fields", []):
            if is_blank(props.get(field)):
                flag(feat, "missing_required", "error", field, None, f"{field} is blank")

        # Domains (allowed values)
        for field, allowed in cfg.get("domains", {}).items():
            value = props.get(field)
            if not is_blank(value) and value not in allowed:
                flag(feat, "invalid_domain", "error", field, value,
                     f"{value!r} is not an allowed value")

        # Numeric ranges
        for field, (lo, hi) in cfg.get("ranges", {}).items():
            value = props.get(field)
            if is_blank(value):
                continue
            try:
                num = float(value)
            except (TypeError, ValueError):
                flag(feat, "not_numeric", "error", field, value, "Value is not a number")
                continue
            if (lo is not None and num < lo) or (hi is not None and num > hi):
                flag(feat, "out_of_range", "warning", field, value,
                     f"Expected between {lo} and {hi}")

        # Dates: parseable, not in the future, and in the right order
        parsed = {}
        for field in cfg.get("date_fields", []):
            d = parse_date(props.get(field))
            if d == "unparseable":
                flag(feat, "bad_date", "error", field, props.get(field), "Date cannot be read")
            elif d and d > today:
                flag(feat, "future_date", "error", field, props.get(field), "Date is in the future")
            parsed[field] = d if isinstance(d, datetime) else None
        for earlier, later in cfg.get("date_order", []):
            a, b = parsed.get(earlier), parsed.get(later)
            if a and b and b < a:
                flag(feat, "date_order", "error", later, props.get(later),
                     f"{later} is before {earlier}")

    return issues


# ---------------------------------------------------------------- output

def write_csv(issues, path):
    cols = ["record_id", "check", "severity", "field", "value", "message"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(issues)


def write_flag_geojson(features, issues, id_field, path):
    """One feature per flagged record, with issue counts for dashboard symbology."""
    by_id = defaultdict(list)
    for i in issues:
        by_id[i["record_id"]].append(i)
    out = []
    for feat in features:
        props = feat.get("properties") or {}
        rid = props.get(id_field, "<no id>")
        if rid in by_id and feat.get("geometry"):
            found = by_id[rid]
            out.append({
                "type": "Feature",
                "geometry": feat["geometry"],
                "properties": {
                    id_field: rid,
                    "qa_errors": sum(1 for i in found if i["severity"] == "error"),
                    "qa_warnings": sum(1 for i in found if i["severity"] == "warning"),
                    "qa_checks": "; ".join(sorted({i["check"] for i in found})),
                },
            })
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": out}, f, indent=2)


def print_summary(features, issues):
    flagged = {i["record_id"] for i in issues}
    total = len(features)
    print(f"Records checked: {total}")
    print(f"Records with issues: {len(flagged)} ({len(flagged) / total:.0%})" if total else "")
    print("Issues by check:")
    for (check, sev), n in sorted(Counter((i["check"], i["severity"]) for i in issues).items()):
        print(f"  {check:<18} {sev:<8} {n}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", required=True, help="QA rules JSON")
    p.add_argument("--source", help="GeoJSON path or feature service layer URL (overrides config)")
    p.add_argument("--boundary", help="City limits GeoJSON for a true point-in-polygon check")
    p.add_argument("--token", help="ArcGIS token for secured services")
    p.add_argument("--out", default="qa_report.csv", help="Issue CSV path")
    p.add_argument("--geojson-out", help="Optional GeoJSON of flagged records")
    p.add_argument("--fail-on-error", action="store_true",
                   help="Exit with code 1 if any error-level issue is found (for scheduled runs)")
    args = p.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    source = args.source or cfg["source"]

    if source.startswith("http"):
        features = load_feature_service(source, token=args.token)
    else:
        features = load_geojson_file(source)
    boundary = load_boundary(args.boundary) if args.boundary else None

    issues = run_checks(features, cfg, boundary_rings=boundary)
    write_csv(issues, args.out)
    if args.geojson_out:
        write_flag_geojson(features, issues, cfg["id_field"], args.geojson_out)

    print_summary(features, issues)
    print(f"Report written to {args.out}")

    if args.fail_on_error and any(i["severity"] == "error" for i in issues):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
