"""Validate a byop/v1 layers dir the way a consumer reads it.

The schema check is only the start: this also opens each layer file, confirms the properties /
columns each metric names actually exist, and checks every metric's fields against its layer's kind.
Heavy geo libraries are optional — without rasterio a GeoTIFF is checked for its magic bytes only.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .presentation import extra_categories_problems, icon_svg_problems, keywords_problems

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "aggregation_spec.schema.json"

# polygon_values geographies a consumer can supply polygons for (CONTRACT.md, "geography").
GEOGRAPHIES = {"census_tract_2020", "zcta_2020", "chicago_ward_2023", "chicago_community_area"}

RULE_FIELDS = {
    "count": {"required": (), "kinds": ("points",)},
    "ratio": {"required": ("numerator", "denominator"), "kinds": ("points",)},
    "share": {"required": ("flag",), "kinds": ("points",)},
    "sum": {"required": ("value",), "kinds": ("points",)},
    "mean": {"required": (), "kinds": ("raster",)},
    "weighted_mean": {"required": ("value", "weight"), "kinds": ("polygon_values",)},
}
CATALOG_FIELDS = ("label", "description", "methodology", "direction")
KNOWN_CATEGORIES = {"physical_environment", "community_vitality", "material_wellbeing", "health", "good_governance",
                    "education", "safety", "time_balance", "psychological_wellbeing", "culture", "other",
                    "social_connectedness", "lifelong_learning", "religion_spiritual"}
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_VALUE = re.compile(r"^\d{4}(-\d{2}-\d{2}([T ].*)?)?$")


def time_value_year(value: Any) -> int | None:
    """The calendar year a `time_field` value falls in (an int year, "YYYY", or an ISO date/datetime);
    None when absent or unparseable. Consumers bucket by this year."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 9999 else None
    if isinstance(value, str) and _TIME_VALUE.match(value.strip()):
        return int(value.strip()[:4])
    return None


class ValidationError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def load_spec(layers_dir: str | Path) -> dict[str, Any]:
    path = Path(layers_dir) / "aggregation_spec.json"
    if not path.exists():
        raise ValidationError([f"{path} does not exist"])
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValidationError([f"aggregation_spec.json is not valid JSON: {error}"]) from error


def _schema_problems(spec: dict[str, Any]) -> list[str]:
    try:
        import jsonschema
    except ImportError:  # the schema check is the same as the hand checks below; degrade gracefully
        return []
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [f"schema: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(spec), key=lambda e: list(e.absolute_path))]


def validate_spec(spec: dict[str, Any], *, strict_catalog: bool = True) -> list[str]:
    """Structural checks that need no files. Returns problems (empty = fine)."""
    problems = _schema_problems(spec)
    if spec.get("contract") != "byop/v1":
        problems.append(f"contract must be 'byop/v1', got {spec.get('contract')!r}")
    layers = spec.get("layers") or {}
    for name, layer in layers.items():
        as_of = (layer or {}).get("as_of")
        if as_of is not None and not (isinstance(as_of, str) and _ISO_DATE.match(as_of)):
            problems.append(f"layer {name!r}: as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}")
    for metric_id, metric in (spec.get("metrics") or {}).items():
        if not isinstance(metric, dict):
            problems.append(f"{metric_id}: must be an object"); continue
        layer_names = metric.get("layer")
        layer_names = layer_names if isinstance(layer_names, list) else [layer_names]
        rule = RULE_FIELDS.get(metric.get("combine"))
        if rule is None:
            problems.append(f"{metric_id}: unknown combine {metric.get('combine')!r}"); continue
        for name in layer_names:
            layer = layers.get(name)
            if layer is None:
                problems.append(f"{metric_id}: layer {name!r} is not declared"); continue
            if layer.get("kind") not in rule["kinds"]:
                problems.append(f"{metric_id}: combine {metric['combine']!r} needs a {'/'.join(rule['kinds'])} layer, {name!r} is {layer.get('kind')!r}")
            if layer.get("kind") == "polygon_values" and not layer.get("id_field"):
                problems.append(f"layer {name!r}: polygon_values layers need an id_field")
            if layer.get("geography") is not None and (layer.get("kind") != "polygon_values"
                                                       or layer["geography"] not in GEOGRAPHIES):
                problems.append(f"layer {name!r}: geography must be one of {sorted(GEOGRAPHIES)} on a polygon_values layer")
        for field in rule["required"]:
            if not metric.get(field):
                problems.append(f"{metric_id}: combine {metric['combine']!r} needs {field!r}")
        if metric.get("time_field"):
            for name in layer_names:
                if (layers.get(name) or {}).get("kind") not in (None, "points"):
                    problems.append(f"{metric_id}: time_field works on points layers only, {name!r} is {layers[name].get('kind')!r}")
        years = metric.get("years")
        if years is not None:
            if not metric.get("time_field"):
                problems.append(f"{metric_id}: years needs a time_field")
            if not (isinstance(years, list) and len(years) == 2 and all(isinstance(y, int) for y in years)
                    and years[0] <= years[1]):
                problems.append(f"{metric_id}: years must be [start, end] with start <= end")
        # v1.4 contested direction: `direction` is the default a reader can flip, so it's needed even when lenient
        if "direction_contested" in metric:
            if not isinstance(metric["direction_contested"], bool):
                problems.append(f"{metric_id}: direction_contested must be true or false, got {metric['direction_contested']!r}")
            elif metric["direction_contested"] and not metric.get("direction"):
                problems.append(f"{metric_id}: direction_contested needs a direction (the default reading a reader can flip)")
        # v1.2 presentation extras: checked even when lenient, because a consumer renders them
        if "keywords" in metric:
            problems.extend(f"{metric_id}: {p}" for p in keywords_problems(metric["keywords"]))
        if "extra_categories" in metric:
            problems.extend(f"{metric_id}: {p}" for p in extra_categories_problems(
                metric["extra_categories"], KNOWN_CATEGORIES - {"other"}, metric.get("category")))
        if "icon_svg" in metric:
            problems.extend(f"{metric_id}: {p}" for p in icon_svg_problems(metric["icon_svg"]))
        if strict_catalog:
            for field in CATALOG_FIELDS:
                if not metric.get(field):
                    problems.append(f"{metric_id}: missing {field!r} (what the dictionary shows readers)")
            if metric.get("category") and metric["category"] not in KNOWN_CATEGORIES:
                problems.append(f"{metric_id}: category {metric['category']!r} is not a Penlight domain (will land in 'other')")
    return problems


def _points_properties(path: Path, limit: int = 2000) -> tuple[set[str], int, list[dict[str, Any]]]:
    """(property names, feature count, the first `limit` features' properties)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features") if isinstance(data, dict) else None
    if data.get("type") != "FeatureCollection" or features is None:
        raise ValidationError([f"{path.name}: not a GeoJSON FeatureCollection"])
    props: set[str] = set()
    sample: list[dict[str, Any]] = []
    for feature in features[:limit]:
        if (feature.get("geometry") or {}).get("type") != "Point":
            raise ValidationError([f"{path.name}: every feature must be a Point (found {(feature.get('geometry') or {}).get('type')!r})"])
        sample.append(feature.get("properties") or {})
        props.update(sample[-1].keys())
    return props, len(features), sample


def _csv_columns(path: Path) -> tuple[set[str], int]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None) or []
        rows = sum(1 for _ in reader)
    return set(header), rows


def _raster_ok(path: Path) -> str | None:
    head = path.read_bytes()[:4]
    if head not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return f"{path.name}: not a TIFF"
    try:
        import rasterio
    except ImportError:
        return None
    with rasterio.open(path) as src:
        if src.crs is None:
            return f"{path.name}: raster has no CRS"
        if src.count < 1:
            return f"{path.name}: raster has no bands"
    return None


def validate_layers_dir(layers_dir: str | Path, *, strict_catalog: bool = True) -> dict[str, Any]:
    """Full check: spec + files + field references. Returns a report; raises ValidationError on problems."""
    layers_dir = Path(layers_dir)
    spec = load_spec(layers_dir)
    problems = validate_spec(spec, strict_catalog=strict_catalog)
    report: dict[str, Any] = {"source": spec.get("source"), "layers": {}, "metrics": list((spec.get("metrics") or {}).keys())}
    fields_by_layer: dict[str, set[str]] = {}
    sample_by_layer: dict[str, list[dict[str, Any]]] = {}
    for name, layer in (spec.get("layers") or {}).items():
        path = layers_dir / str(layer.get("file", ""))
        if not path.exists():
            problems.append(f"layer {name!r}: file {layer.get('file')!r} is missing"); continue
        size_mb = path.stat().st_size / 1e6
        try:
            if layer.get("kind") == "points":
                fields, n, sample_by_layer[name] = _points_properties(path); fields_by_layer[name] = fields
                report["layers"][name] = {"kind": "points", "features": n, "mb": round(size_mb, 1)}
            elif layer.get("kind") == "polygon_values":
                fields, n = _csv_columns(path); fields_by_layer[name] = fields
                if layer.get("id_field") and layer["id_field"] not in fields:
                    problems.append(f"layer {name!r}: id_field {layer['id_field']!r} is not a column")
                report["layers"][name] = {"kind": "polygon_values", "rows": n, "mb": round(size_mb, 1)}
            elif layer.get("kind") == "raster":
                err = _raster_ok(path)
                if err: problems.append(err)
                report["layers"][name] = {"kind": "raster", "mb": round(size_mb, 1)}
        except ValidationError as error:
            problems.extend(error.problems)
        if size_mb > 500:
            problems.append(f"layer {name!r}: {size_mb:.0f} MB exceeds the 500 MB consumer cap — publish a documented sample")
    for metric_id, metric in (spec.get("metrics") or {}).items():
        if not isinstance(metric, dict): continue
        names = metric.get("layer"); names = names if isinstance(names, list) else [names]
        for name in names:
            fields = fields_by_layer.get(name)
            if fields is None: continue
            for key in ("numerator", "denominator", "flag", "value", "weight"):
                if metric.get(key) and metric[key] not in fields:
                    problems.append(f"{metric_id}: {key} {metric[key]!r} is not a property/column of layer {name!r}")
            for col in metric.get("ci") or []:
                if col not in fields:
                    problems.append(f"{metric_id}: ci column {col!r} is not in layer {name!r}")
            time_field = metric.get("time_field")
            if time_field and name in sample_by_layer:
                if time_field not in fields:
                    problems.append(f"{metric_id}: time_field {time_field!r} is not a property of layer {name!r}")
                    continue
                values = [p.get(time_field) for p in sample_by_layer[name]]
                bad = [v for v in values if v not in (None, "") and time_value_year(v) is None]
                if bad:
                    problems.append(f"{metric_id}: time_field {time_field!r} has values that are not a year or ISO date, e.g. {bad[0]!r}")
                elif not any(time_value_year(v) for v in values):
                    problems.append(f"{metric_id}: time_field {time_field!r} is empty on every sampled point")
    if problems:
        raise ValidationError(problems)
    return report
