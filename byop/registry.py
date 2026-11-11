"""measures.json — the registry of admitted sources, pinned to release assets by sha256."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

# The checkout's own measures.json when byop runs from source; an installed byop reads ./measures.json.
_CHECKOUT_REGISTRY = Path(__file__).resolve().parents[1] / "measures.json"
REGISTRY_PATH = _CHECKOUT_REGISTRY if _CHECKOUT_REGISTRY.exists() else Path("measures.json")
TARGETS = {"ward", "community_area", "chi"}
CONFIDENCE = {"high", "medium", "low"}
ENTRY_KEYS = {"name", "repo", "tag", "assets", "targets", "allocation_method", "confidence", "enabled", "pending_release", "notes", "layers_subdir"}


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_registry(registry: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if registry.get("contract") != "byop/v1":
        problems.append("registry contract must be byop/v1")
    names = set()
    for entry in registry.get("measures", []):
        name = entry.get("name", "<unnamed>")
        if name in names: problems.append(f"{name}: duplicate entry")
        names.add(name)
        unknown = set(entry) - ENTRY_KEYS
        if unknown: problems.append(f"{name}: unknown keys {sorted(unknown)}")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(entry.get("repo", ""))):
            problems.append(f"{name}: repo must be owner/name")
        if not set(entry.get("targets", [])) <= TARGETS or not entry.get("targets"):
            problems.append(f"{name}: targets must be a non-empty subset of {sorted(TARGETS)}")
        if entry.get("confidence", "medium") not in CONFIDENCE:
            problems.append(f"{name}: confidence must be one of {sorted(CONFIDENCE)}")
        if entry.get("pending_release"):
            continue
        if not entry.get("tag"): problems.append(f"{name}: tag is required once released")
        assets = entry.get("assets") or {}
        if "aggregation_spec.json" not in assets:
            problems.append(f"{name}: assets must include aggregation_spec.json")
        for asset, digest in assets.items():
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(digest)):
                problems.append(f"{name}: {asset}: digest must be 'sha256:<64 hex>'")
    return problems


def release_asset_url(repo: str, tag: str, asset: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{asset}"


def sha256_of_url(url: str, max_bytes: int = 500_000_000) -> str:
    digest, total = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - github.com release URLs only
        while chunk := resp.read(1 << 20):
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"{url}: exceeds {max_bytes} bytes")
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def pin(repo: str, tag: str, assets: list[str]) -> dict[str, str]:
    """{asset: sha256} for a release — what goes into measures.json."""
    for asset in assets:
        if not asset.startswith(("https://github.com/",)) and "/" in asset:
            raise ValueError("asset names are bare file names")
    return {asset: sha256_of_url(release_asset_url(repo, tag, asset)) for asset in assets}
