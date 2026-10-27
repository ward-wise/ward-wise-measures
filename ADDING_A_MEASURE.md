# Adding a measure to Penlight

You don't need access to anything of Penlight's. You need a public repo, a computed layer, and one
pull request here.

## 1. Compute something fine-grained

Points (one row per thing, with the properties your metrics need), a raster, or a table of values on
census tracts / ZCTAs. Keep the raw inputs in your repo or document where they come from; publish
the finest layer you're comfortable publishing (a documented sample is fine for huge layers).

## 2. Write `aggregation_spec.json`

Follow [`CONTRACT.md`](CONTRACT.md). Every metric needs a `label`, a one-sentence `description`, a
`methodology`, a `unit` and a `direction`. If residents reasonably disagree about which way is better
(more plate readers: safer or more watched?), keep a default `direction` and add
`"direction_contested": true` so each reader can flip it. Put the spec next to the layer files, e.g.
`data/layers/`.

## 3. Validate locally

```bash
pip install git+https://github.com/HarryBrisson/ward-wise-measures
byop validate data/layers
```

It checks the schema, that every file exists and parses, that metric fields match the layer kind,
and prints the metrics the way a consumer sees them.

## 4. Publish a release

**If your layers are built on your own machine** (rasters, large CSVs you don't commit), publish from
there. It validates, creates the release, uploads exactly the files the spec names, and prints your
registry entry with the sha256 pins:

```bash
byop publish data/layers --repo you/your-measure --tag v2026.10.13 --targets community_area,chi
byop publish data/layers --repo you/your-measure --tag v2026.10.13 --dry-run   # check first
```

**If CI can build or already has the layers** (they're committed, or a workflow produces them), add
this workflow to your repo as `.github/workflows/publish.yml`:

```yaml
name: publish measure
on:
  push:
    tags: ["v*"]
jobs:
  publish:
    uses: HarryBrisson/ward-wise-measures/.github/workflows/publish-measure.yml@main
    with:
      layers_dir: data/layers
    permissions:
      contents: write
```

Then `git tag v2026.10.07 && git push --tags`. The workflow validates the spec, uploads every file in
the layers dir to the release, and prints the sha256 of each asset.

## 5. Open a pull request here

Add your entry to `measures.json` (`byop publish` printed it for you):

```json
{
  "name": "sunscore",
  "repo": "HarryBrisson/sunscore",
  "tag": "v2026.10.07",
  "assets": {
    "aggregation_spec.json": "sha256:…",
    "sun_access_annual.tif": "sha256:…"
  },
  "targets": ["ward", "community_area", "chi"],
  "allocation_method": "native_source_byop",
  "confidence": "medium"
}
```

`targets` are the Penlight geographies you want values for. `confidence` is `high` / `medium` / `low`;
modeled estimates are `low` and set `allocation_method` to `modeled_synthetic_sae`. CI validates the
entry and checks the sha256s against the release. A maintainer merges; the next pipeline run
ingests your measure, and it appears in the dictionary with your methodology text and, if you set
`nominator`, the ward credit.

## Updating

Tag a new release, run `byop pin <repo> <tag>` to regenerate your entry's sha256s, and open a PR
with the bump. Nothing changes in Penlight until it's merged.
