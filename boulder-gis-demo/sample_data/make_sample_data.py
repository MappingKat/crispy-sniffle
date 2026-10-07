"""Build small SYNTHETIC test layers with planted errors so qa_check.py can be demoed offline.
These are not real Boulder permits."""
import json, random
from pathlib import Path

random.seed(7)
HERE = Path(__file__).parent
STREETS = ["Pearl St", "Broadway", "Arapahoe Ave", "Baseline Rd", "Folsom St", "Table Mesa Dr", "Iris Ave", "28th St"]
TYPES = ["Single Family Detached Dwelling Building", "Accessory Building", "Electrical", "Roofing Replacement",
         "Mechanical", "Fence and Wall", "Demolition", "Sign"]

def pt(lon, lat):
    return {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}

permits = []
for i in range(1, 61):
    applied = f"2026-{random.randint(1, 6):02d}-{random.randint(1, 28):02d}"
    issued = f"2026-{random.randint(7, 8):02d}-{random.randint(1, 28):02d}"
    permits.append({"type": "Feature",
        "geometry": pt(random.uniform(-105.28, -105.20), random.uniform(39.98, 40.06)),
        "properties": {"PERMIT_NUM": f"PMT2026-{i:05d}", "PERMIT_TYPE": random.choice(TYPES),
            "STATUS": random.choice(["Issued", "Finaled", "In Review"]),
            "ADDRESS": f"{random.randint(100, 3999)} {random.choice(STREETS)}",
            "APPLIED_DATE": applied, "ISSUED_DATE": issued, "FINALED_DATE": None,
            "VALUATION": random.randint(2000, 900000)}})

# Planted errors
p = permits
p[3]["properties"]["PERMIT_NUM"] = p[2]["properties"]["PERMIT_NUM"]           # duplicate_id
p[5]["geometry"] = None                                                       # missing_geometry
p[7]["geometry"] = pt(-104.99, 39.74)                                          # outside_boundary (Denver)
p[9]["properties"]["ADDRESS"] = ""                                              # missing_required
p[11]["properties"]["STATUS"] = "issued "                                       # invalid_domain
p[13]["properties"]["ISSUED_DATE"] = "2025-12-01"                               # date_order
p[15]["properties"]["FINALED_DATE"] = "2027-03-15"                              # future_date
p[17]["properties"]["VALUATION"] = -500                                         # out_of_range
p[19]["properties"]["APPLIED_DATE"] = "13/45/2026"                              # bad_date
p[21]["geometry"] = dict(p[20]["geometry"])                                     # stacked_point

checks = []
for i, permit in enumerate(p[:20]):
    if not permit["geometry"]:
        continue
    lon, lat = permit["geometry"]["coordinates"]
    checks.append({"type": "Feature", "geometry": pt(lon + 0.0001, lat + 0.0001),
        "properties": {"globalid": f"{{SC-{i:04d}}}", "permit_num": permit["properties"]["PERMIT_NUM"],
            "visit_date": "2026-09-2" + str(i % 9), "inspector": random.choice(["kengelsted", "jdoe"]),
            "site_status": random.choice(["active_construction", "not_started", "complete"]),
            "permit_card_posted": random.choice(["yes", "no"]),
            "erosion_control": random.choice(["in_place", "deficient", "not_required"]),
            "row_obstruction": random.choice(["yes", "no"])}})
checks[2]["properties"]["inspector"] = None                                     # missing_required
checks[4]["properties"]["site_status"] = "Active"                               # invalid_domain
checks[6]["properties"]["visit_date"] = "2027-01-01"                            # future_date

for name, feats in [("sample_permits", p), ("sample_site_checks", checks)]:
    (HERE / f"{name}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, indent=1))
    print(f"wrote {name}.geojson ({len(feats)} features)")
