# Boulder Permit Site Check

A small, end-to-end ArcGIS demo built for the City of Boulder GIS role in Planning & Development Services.

**The idea:** Boulder issues thousands of construction permits a year. Staff visit sites to confirm work matches the permit. This demo shows how GIS supports that loop. Open data comes in. Staff collect in the field. Python checks the data. A dashboard shows status. A StoryMap explains it.

| Posting skill | Where it shows up |
| --- | --- |
| ArcGIS Pro, geodatabase design | Step 1 |
| Survey123 | Step 2 |
| Field Maps | Step 3 |
| Experience Builder / dashboards | Step 4 |
| Python, data quality | Step 5 |
| Communicating with non-GIS staff | Step 6 |

---

## Step 1. ArcGIS Pro: bring in Boulder data

**Data (City of Boulder Open Data):**
- Construction permits (points). Check field names against the city's [construction permits data dictionary](https://webappsprod.bouldercolorado.gov/opendata/construction_permits_data_dictionary.pdf).
- Zoning districts (polygons): `gis.bouldercolorado.gov/ags_svr1/rest/services/plan/ZoningDistricts/MapServer/0`
- City limits (polygon).

**In Pro:**
1. Create `BoulderPermitSiteCheck.gdb`. Project everything to NAD 1983 StatePlane Colorado North (US Feet), WKID 2876.
2. Load permits. Filter to permits issued in the last 12 months that need site work (building, demolition, fence, right-of-way).
3. Spatial Join permits to zoning. Each permit now carries its zone district.
4. Add attribute domains for `STATUS` and `PERMIT_TYPE`. This is the same list the QA script checks.
5. Share as a hosted feature layer: `Boulder_Permits_Active` (view only).

*Interview line:* "I set domains in the geodatabase so bad values are blocked at entry. The script catches what gets in anyway."

## Step 2. Survey123: the site check form

The form is in [`survey123/boulder_permit_site_check.xlsx`](survey123/). Rebuild it with `python survey123/build_xlsform.py`.

1. Open the XLSX in Survey123 Connect. Publish. This creates the `Permit_Site_Check` hosted layer.
2. What the form does:
   - `permit_num` has a format constraint (`PMT2026-00001`).
   - Visit date cannot be in the future.
   - Erosion and right-of-way questions only show for active construction.
   - A photo is required when something is deficient.
   - A hidden `followup_needed` field is set to yes when anything fails. The dashboard uses it.

## Step 3. Field Maps: collect in the field

1. Make a web map with `Boulder_Permits_Active`, zoning, and the `Permit_Site_Check` layer.
2. Add a second editable layer, `Field_Observations`, for things not tied to a permit. Example types: possible unpermitted work, sign issue, sidewalk blocked. Build its form in Field Maps Designer.
3. In the permit pop-up, add a link that opens Survey123 with the permit filled in:
   ```
   arcgis-survey123://?itemID=<SURVEY_ITEM_ID>&field:permit_num={PERMIT_NUM}&field:address={ADDRESS}&center={latitude},{longitude}
   ```
4. Enable offline areas. Collect 10 to 15 real points on a walk around downtown or North Boulder. Only record what is visible from the public right-of-way.

*Interview line:* "The inspector taps a permit, taps 'Start site check,' and the form opens already filled in. No retyping permit numbers."

## Step 4. Experience Builder: the dashboard

One page. Three sections.
- **Map:** permits colored by site check status. QA flags as a separate layer.
- **Indicators:** permits checked vs. not yet checked. Sites needing follow-up. Open QA errors.
- **Charts and list:** site checks by zone district. Follow-ups by type. A table of flagged records.

Add a filter by zone district and permit type. Link the map, charts, and list so a click in one filters the others.

## Step 5. Python: data quality check

The script is [`qa/qa_check.py`](qa/qa_check.py). Standard library only. It runs in ArcGIS Pro's Python or any Python 3.9+.

Rules live in JSON. One config for the permits layer. One for the field layer.

| Check | Catches |
| --- | --- |
| `missing_geometry` | Records with no location |
| `outside_boundary` | Points outside city limits (bounding box, or a real boundary with `--boundary`) |
| `stacked_point` | Two records at the exact same spot |
| `missing_id`, `duplicate_id` | Missing or repeated permit numbers |
| `missing_required` | Blank required fields |
| `invalid_domain` | Values not in the allowed list (e.g. `"issued "` with a trailing space) |
| `out_of_range`, `not_numeric` | Negative valuation, text in a number field |
| `bad_date`, `future_date`, `date_order` | Unreadable dates, future dates, issued before applied |

**Try it offline** with synthetic sample data (planted errors, not real permits):

```bash
python sample_data/make_sample_data.py
cd qa
python qa_check.py --config qa_config_permits.json --out ../sample_data/qa_report_permits.csv \
    --geojson-out ../sample_data/qa_flags_permits.geojson
```

Output:
```
Records checked: 60
Records with issues: 11 (18%)
Issues by check:
  bad_date           error    1
  date_order         error    1
  duplicate_id       error    2
  future_date        error    1
  invalid_domain     error    1
  missing_geometry   error    1
  missing_required   error    1
  out_of_range       warning  1
  outside_boundary   error    1
  stacked_point      warning  2
```

**Against live layers:**
```bash
python qa_check.py --config qa_config_site_checks.json \
    --source https://services.arcgis.com/<org>/arcgis/rest/services/Permit_Site_Check/FeatureServer/0 \
    --token <token> --out qa_report.csv --geojson-out qa_flags.geojson --fail-on-error
```

Upload `qa_flags.geojson` as the QA flags layer in the dashboard. `--fail-on-error` returns exit code 1, so a scheduled task or Notebook can alert someone.

**Next step if there's time:** run it nightly as an ArcGIS Online Notebook task and overwrite the flags layer.

## Step 6. StoryMap: explain it

Short. Five sections.
1. **The problem.** Permits are issued at a desk. The work happens on a site. Someone has to connect the two.
2. **The data.** Map of active permits by zone. One sentence on where the data comes from.
3. **In the field.** Screenshots of Field Maps and the Survey123 form. One photo from the walk.
4. **Keeping data clean.** The QA table. One before and after example.
5. **What it shows.** The dashboard embedded. Two or three plain-language findings.

Write it for a planner or a council member, not a GIS analyst.

---

## Build plan (about two weekends)

| Day | Work |
| --- | --- |
| 1 | Pro project, data, domains, publish permits layer |
| 2 | Publish Survey123 form. Build Field Maps web map and pop-up link |
| 3 | Field walk. Collect 10 to 15 points |
| 4 | Run QA script on both layers. Fix issues. Publish flags layer |
| 5 | Experience Builder dashboard |
| 6 | StoryMap. Record a 3-minute screen video as backup |

## 5-minute interview walkthrough

1. **StoryMap first (30 sec).** "Here's the problem I picked and why it matters to PDS."
2. **Pro (1 min).** The geodatabase, domains, and the spatial join to zoning.
3. **Field Maps and Survey123 (1.5 min).** Tap a permit. Open the prefilled form. Show the conditional questions.
4. **Python (1 min).** Run the script live. Show the report. Point to one real error it caught.
5. **Dashboard (1 min).** Filter by zone. Show follow-ups. "This is what a supervisor would open on Monday."

Close with: "Every piece is small. The point is they connect. Data in, field check, QA, decision."

## Notes

- Field names in the configs and sample data are placeholders. Match them to the real permits schema first.
- Do not collect private property details or photos of people. Stay on the public right-of-way.
- Sample data in `sample_data/` is synthetic. Say so if you show it.
