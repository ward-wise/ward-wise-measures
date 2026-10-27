# The byop/v1 contract

A measure source publishes a folder (the *layers dir*) containing `aggregation_spec.json` and the
files it names. A consumer reads only that folder and aggregates each metric to whatever target
polygons it holds. Nothing about the consumer's geography is baked into the source: the same
release serves Chicago wards, community areas, a square-mile grid, or another city's districts.

## aggregation_spec.json

```json
{
  "contract": "byop/v1",
  "source": "sunscore",
  "source_url": "https://github.com/HarryBrisson/sunscore",
  "layers": {
    "sun_annual": {"file": "sun_access_annual.tif", "kind": "raster",
                   "value": "per-cell direct-sun fraction, NaN off the ground mask"}
  },
  "metrics": {
    "annual_sun_access_pct": {
      "layer": "sun_annual", "combine": "mean", "scale": 100,
      "unit": "percent", "direction": "higher",
      "label": "Sun Access",
      "description": "Share of daylight that ground-level spots receive direct sun, averaged over the year.",
      "methodology": "Simulate the sun across the day and seasons over a 2022 LiDAR surface model …",
      "category": "physical_environment",
      "default_weight": 0.5,
      "nominator": {"name": "Jackie Schmitz", "ward_id": "43"}
    }
  },
  "fixed_geography_metrics": {
    "permit_zone_block_faces_per_sqkm": "ward-tagged address ranges with no point geometry"
  }
}
```

### Top level

| Field | Required | Meaning |
|---|---|---|
| `contract` | yes | exactly `"byop/v1"` |
| `source` | yes | short slug, `[a-z0-9_-]+`; the registry key |
| `source_url` | recommended | the repo |
| `layers` | yes | the fine data files, by name |
| `metrics` | yes | what to compute from them, by `metric_id` |
| `fixed_geography_metrics` | no | metrics the source can only report on its own geography, with a one-line reason; consumers may estimate them |
| `synthetic_estimate`, `caveat` | no | set `synthetic_estimate: true` and explain when values are modeled rather than measured (consumers label them and lower their confidence) |

Any other top-level keys are kept as provenance and ignored by consumers.

### Layers

| `kind` | File | Geometry | Used by |
|---|---|---|---|
| `points` | GeoJSON FeatureCollection of Point features with `properties` | its own | `count`, `ratio`, `share`, `sum` |
| `raster` | GeoTIFF, any projected CRS, NaN = no data | its own | `mean` |
| `polygon_values` | CSV with an `id_field` column naming a standard polygon (tract GEOID, ZCTA, ward, community area) and one column per value/weight | the consumer supplies the geometries | `weighted_mean` |

Each layer: `file` (relative to the spec), `kind`, optional `value` (a human sentence describing one
cell/point/row), for `polygon_values` the `id_field` and a recommended `geography`, and optional
`as_of` (see [Time](#time-v11-optional)).

**`geography`** (`polygon_values` only, v1.3) says which polygons the ids name, so a consumer can
supply them without being told per source:

| `geography` | `id_field` values |
|---|---|
| `census_tract_2020` | 11-digit 2020 tract GEOID (`17031010100`) |
| `zcta_2020` | 5-digit 2020 ZCTA |
| `chicago_ward_2023` | two-digit ward on the 2023 map (`01` … `50`) |
| `chicago_community_area` | two-digit community area (`01` … `77`) |

A Chicago ward or community-area layer is used only for that same geography (a ward table never
stands in for a neighborhood); census layers serve any target by overlap. To publish one measure
exactly at the city's own boundaries and by overlap everywhere else, list the layers finest-first
in the metric — `"layer": ["wards", "community_areas", "tracts"]` — and the consumer takes the first
one it has polygons for.

### Metrics

| Field | Required | Meaning |
|---|---|---|
| `layer` | yes | a layer name, or a list of names when the same metric is published at several geographies (`["tract", "zcta"]`) |
| `combine` | yes | one of the rules below |
| `unit` | yes | `percent`, `count`, `rate`, `currency`, `index_0_100`, `minutes`, `miles`, … (Penlight's units; free text is accepted but won't format) |
| `direction` | yes | `higher` or `lower` = which way is better for a resident (`higher_better` / `lower_better` accepted) |
| `direction_contested` | no | `true` when residents reasonably disagree about which way is better; `direction` stays the default reading and each reader may flip it, see [Contested direction](#contested-direction-v14-optional) |
| `label` | yes | 1–3 words, the chip on the map |
| `description` | yes | one sentence a resident understands |
| `methodology` | yes | how it was computed, 1–3 sentences, with the data source |
| `category` | recommended | a Penlight domain: `physical_environment`, `community_vitality`, `material_wellbeing`, `health`, `good_governance`, `education`, `safety`, `time_balance`, `psychological_wellbeing`, `culture`, `social_connectedness`, `lifelong_learning`, `religion_spiritual`; unknown categories land in `other` |
| `default_weight` | no | 0–1; weight in the default index (0 = available but not weighted in) |
| `nominator` | no | `{"name": ..., "ward_id": "43"}` — the resident who proposed the measure, credited on the map |
| `scale`, `per`, `flag`, `numerator`, `denominator`, `value`, `weight`, `ci` | per rule | see below |
| `time_field`, `years` | no | per-year output for points metrics, see [Time](#time-v11-optional) |
| `time_invariant`, `valid_from` | no | catalog hints: the value doesn't change year to year / isn't meaningful before this year (`YYYY` or ISO date) |
| `keywords`, `extra_categories`, `icon_svg` | no | how the metric is found and drawn in the picker, see [Presentation](#presentation-v12-optional) |

### Combine rules

| `combine` | Layer kind | Result for a target polygon |
|---|---|---|
| `count` | points | number of points inside ÷ `per` (`"area_km2"`, or omit for a raw count) |
| `ratio` | points | Σ `numerator` ÷ Σ `denominator` over points inside, × `scale` (default 1) |
| `share` | points | fraction of points inside whose `flag` property is truthy, × `scale` (default 100) |
| `sum` | points | Σ `value` property over points inside ÷ `per` (`"area_km2"`, or omit for a raw sum) — *v1.1* |
| `mean` | raster | area-weighted mean of the cells inside, NaN ignored, × `scale` (default 1) |
| `weighted_mean` | polygon_values | Σ(`weight` · overlap · `value`) ÷ Σ(`weight` · overlap) over source polygons overlapping the target |

A target with nothing inside gets no value (not zero).

## Time (v1.1, optional)

Without these fields a metric is one undated reading per target, which a consumer dates by when it
collected it. That's right for a slow-moving surface (sun access) but throws away the history in a
stream of dated events (rezonings, sales, permits), and an undated reading can't enter year-over-year
analysis. Two optional fields fix that; a consumer that predates them still reads the spec and gets the
all-years total, so adding them never breaks anyone.

- **`time_field`** (metric, `points` layers only): a property holding each point's date — an integer
  year, `"YYYY"`, or an ISO date/datetime (`"2024-06-12"`). The consumer applies the combine rule
  **per calendar year**, giving one value per (target, year). Points whose `time_field` is empty or
  null are left out of that metric. A target-year with no points gets no value, as above — except
  `count` and `sum`, where a year inside the metric's range with nothing inside is a real zero once the
  target has any point in any year.
- **`years`** (metric, needs `time_field`): `[start, end]`, inclusive, bounding which years are
  reported — use it to stop before a year the source doesn't fully cover.
- **`as_of`** (layer): an ISO date the layer describes (a zoning map downloaded on that date). The
  consumer dates every untimed metric on that layer to `as_of` instead of to its collection time.

The current calendar year is partial; consumers mark it so (Penlight: `metadata.partial_year`).

## Presentation (v1.2, optional)

The catalog fields above are enough to put a metric on the map. Three more let it arrive looking as
finished as a hand-curated one, with no change to the consumer's code. Each is optional and checked by
the validator even with `--lenient`, because the consumer renders them.

- **`keywords`**: lowercase, space-separated words a resident might search for that the label and
  description don't already say — `"movie movies film theater cinema screens"`. Letters, digits,
  spaces and `. , % $ & ' + / -`; at most 300 characters. Be generous: synonyms, plurals, what people
  call it.
- **`extra_categories`**: up to 4 more Penlight domains (the `category` list above, not `other`) the
  metric should also be listed under. `category` stays its primary domain for scoring; these only change
  where it is found.
- **`icon_svg`**: the glyph's inner SVG markup, drawn in a `0 0 20 20` box. The consumer wraps it in
  `<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"
  stroke-linejoin="round">`, so draw with strokes and leave colour to `currentColor` (`fill="currentColor"`
  for a solid dot). Only shapes are allowed — `g`, `path`, `circle`, `ellipse`, `line`, `polyline`,
  `polygon`, `rect` — with geometry and paint attributes (`d`, `cx`, `points`, `transform`, `fill`,
  `stroke-width`, …); no `<script>`, `<foreignObject>`, `<use>`, `<image>` or text, no `on*` handlers,
  no `href`/`xlink:href`, no `url(…)`, no comments or entities; at most 2,048 characters.

```json
"cinemas_count": {
  "…": "…",
  "keywords": "movie movies film theater theatre cinema multiplex",
  "extra_categories": ["community_vitality"],
  "icon_svg": "<rect x=\"3\" y=\"4\" width=\"14\" height=\"9\" rx=\"1\"/><line x1=\"7\" y1=\"16.5\" x2=\"13\" y2=\"16.5\"/>"
}
```

A consumer's own curated glyph or tags for a metric take priority; the spec's are the default. Penlight
merges `keywords` and `extra_categories` with its hand-kept lists and uses `icon_svg` only when it has no
hand-drawn glyph, falling back to the metric's domain glyph when the spec has none either.

## Contested direction (v1.4, optional)

Most measures have a direction residents agree on: fewer crashes is better. Some don't. More
license-plate readers is less privacy to one reader and more public safety to the next; more bars is
nightlife to one and nuisance to another. For a measure like that, the source still picks a `direction`,
and says the choice is open:

```json
"alpr_per_sqkm": {
  "…": "…",
  "direction": "lower",
  "direction_contested": true,
  "default_weight": 0,
  "methodology": "… Fewer readers is scored as better by default, a privacy reading; others count the same cameras as a public-safety investment."
}
```

- **`direction_contested`** (metric, boolean): `true` means the consumer should let each reader choose
  which way counts as better for this metric. `direction` is still required (even with `--lenient`): it is
  the default every reader starts from and the reading an older consumer uses. `false` is the same as
  leaving the field out.
- A consumer that offers the choice scores the flipped metric as if its `direction` were the other one.
  For min-max scoring that is `score → 100 − score`; nothing else about the metric changes.
- Say in `methodology` which reading the default takes and what the other one is, and leave
  `default_weight` at 0 so no reading enters anyone's index unasked (both recommended, not enforced).

Penlight shows a "fewer is better / more is better" switch on contested metrics and carries each
reader's choice in the page URL, so a shared link scores the same way.

## Publishing

Attach the layers dir's files, flat, to a GitHub Release of the source repo, tagged
`vYYYY.MM.DD` or semver. `aggregation_spec.json` must be one of the assets. The reusable workflow in
this repo does it: see `ADDING_A_MEASURE.md`. Size limits: 2 GB per asset (GitHub's), and a consumer
may cap what it downloads (Penlight: 500 MB per asset). Big point layers can publish a documented
sample (rentrate publishes a parcel-digit sample of its 1.6 M parcels).

## Versioning

`byop/v1` is frozen: new optional fields may be added, nothing required changes. A breaking change
becomes `byop/v2` and consumers announce support before sources need it.

| Revision | Added (all optional) |
|---|---|
| v1.1 (validator 0.2.0) | `sum` combine; metric `time_field`, `years`, `time_invariant`, `valid_from`; layer `as_of` |
| v1.2 (validator 0.3.0) | metric `keywords`, `extra_categories`, `icon_svg` (presentation); `social_connectedness`, `lifelong_learning`, `religion_spiritual` accepted as categories |
| v1.3 (validator 0.3.0) | layer `geography` on `polygon_values` layers |
| v1.4 (validator 0.4.0) | metric `direction_contested` |

A source that uses a v1.1, v1.2, v1.3 or v1.4 field still says `"contract": "byop/v1"`. Before a source relies on one,
the consumer must support it (Penlight does once its pipeline reads `time_field`) — an older consumer
rejects `sum` and ignores the time, presentation and contested-direction fields (its schema check passes them through
as unknown keys), so a contested metric simply scores in its default `direction` there.
