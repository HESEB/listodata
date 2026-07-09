#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply admin approved patches for HESEB Livestock Terminal.

Phase 6-8 uses a static-site-safe workflow:
1. Admin page generates a JSON patch bundle.
2. Operator commits the bundle to app/data/admin/approved_patches.json.
3. This script applies approved patches to filter_dictionary.json and
   classification_overrides.json during the scheduled workflow.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "app" / "data" / "admin"
PATCH_FILE = ADMIN / "approved_patches.json"
DICT_FILE = ADMIN / "filter_dictionary.json"
OVERRIDE_FILE = ADMIN / "classification_overrides.json"
STATUS_FILE = ADMIN / "patch_status.json"
ANALYSIS_STATUS_FILE = ROOT / "app" / "data" / "analysis" / "patch_status.json"

VALID_ACTIONS = {
    "add_exclude_keyword",
    "add_include_keyword",
    "add_species_keyword",
    "force_include",
    "force_exclude",
    "change_species",
    "edit_impact",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_unique(arr: list, value) -> bool:
    if value in arr:
        return False
    arr.append(value)
    return True


def ensure_dict(d: dict) -> dict:
    d.setdefault("exclude_keywords", [])
    d.setdefault("include_keywords", [])
    d.setdefault("species_keywords", {})
    for sp in ["BEEF", "PORK", "POULTRY", "DUCK", "EGG", "OTHER"]:
        d["species_keywords"].setdefault(sp, [])
    return d


def ensure_overrides(o: dict) -> dict:
    o.setdefault("policy", "phase6_classification_overrides_v1")
    o.setdefault("force_include", [])
    o.setdefault("force_exclude", [])
    o.setdefault("species_overrides", [])
    o.setdefault("impact_overrides", [])
    return o


def patch_id(p: dict) -> str:
    return str(p.get("id") or p.get("title") or p.get("keyword") or p.get("target") or "")[:120]


def apply_patch(p: dict, dictionary: dict, overrides: dict) -> tuple[str, str]:
    if not p.get("approved"):
        return "skipped", "approved=false"
    action = p.get("action")
    if action not in VALID_ACTIONS:
        return "failed", f"invalid action: {action}"

    if action == "add_exclude_keyword":
        kw = str(p.get("keyword") or "").strip()
        if not kw:
            return "failed", "keyword missing"
        changed = add_unique(dictionary["exclude_keywords"], kw)
        return ("applied" if changed else "skipped", "exclude keyword added" if changed else "already exists")

    if action == "add_include_keyword":
        kw = str(p.get("keyword") or "").strip()
        if not kw:
            return "failed", "keyword missing"
        changed = add_unique(dictionary["include_keywords"], kw)
        return ("applied" if changed else "skipped", "include keyword added" if changed else "already exists")

    if action == "add_species_keyword":
        sp = str(p.get("species") or "").strip().upper()
        kw = str(p.get("keyword") or "").strip()
        if not sp or not kw:
            return "failed", "species/keyword missing"
        dictionary["species_keywords"].setdefault(sp, [])
        changed = add_unique(dictionary["species_keywords"][sp], kw)
        return ("applied" if changed else "skipped", "species keyword added" if changed else "already exists")

    if action == "force_include":
        target = str(p.get("target") or p.get("title") or "").strip()
        if not target:
            return "failed", "target missing"
        row = {"target": target, "reason": p.get("reason") or "admin approved", "created_at": now_iso()}
        changed = add_unique(overrides["force_include"], row)
        return ("applied" if changed else "skipped", "force include added" if changed else "already exists")

    if action == "force_exclude":
        target = str(p.get("target") or p.get("title") or "").strip()
        if not target:
            return "failed", "target missing"
        row = {"target": target, "reason": p.get("reason") or "admin approved", "created_at": now_iso()}
        changed = add_unique(overrides["force_exclude"], row)
        return ("applied" if changed else "skipped", "force exclude added" if changed else "already exists")

    if action == "change_species":
        target = str(p.get("target") or p.get("title") or "").strip()
        species = p.get("species") or p.get("to_species")
        if not target or not species:
            return "failed", "target/species missing"
        row = {"target": target, "species": species if isinstance(species, list) else [str(species).upper()], "reason": p.get("reason") or "admin approved", "created_at": now_iso()}
        changed = add_unique(overrides["species_overrides"], row)
        return ("applied" if changed else "skipped", "species override added" if changed else "already exists")

    if action == "edit_impact":
        target = str(p.get("target") or p.get("title") or "").strip()
        impact = p.get("impact")
        direction = p.get("direction")
        if not target:
            return "failed", "target missing"
        row = {"target": target, "impact": impact, "direction": direction, "reason": p.get("reason") or "admin approved", "created_at": now_iso()}
        changed = add_unique(overrides["impact_overrides"], row)
        return ("applied" if changed else "skipped", "impact override added" if changed else "already exists")

    return "failed", "unhandled action"


def main() -> int:
    patches_doc = read_json(PATCH_FILE, {"patches": []})
    dictionary = ensure_dict(read_json(DICT_FILE, {}))
    overrides = ensure_overrides(read_json(OVERRIDE_FILE, {}))
    patches = patches_doc.get("patches", []) if isinstance(patches_doc, dict) else []
    results = []
    for p in patches:
        if not isinstance(p, dict):
            results.append({"id": "invalid", "status": "failed", "message": "patch is not object"})
            continue
        status, message = apply_patch(p, dictionary, overrides)
        results.append({"id": patch_id(p), "action": p.get("action"), "status": status, "message": message})

    dictionary["updated_at"] = now_iso()
    dictionary["last_patch_policy"] = "phase6_admin_patch_apply_v1"
    overrides["updated_at"] = now_iso()
    overrides["last_patch_policy"] = "phase6_admin_patch_apply_v1"

    if patches:
        write_json(DICT_FILE, dictionary)
        write_json(OVERRIDE_FILE, overrides)

    applied = sum(1 for r in results if r["status"] == "applied")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")
    payload = {
        "updated_at": now_iso(),
        "policy": "phase6_admin_patch_status_v1",
        "summary": {
            "patch_count": len(results),
            "applied_count": applied,
            "skipped_count": skipped,
            "failed_count": failed,
            "status": "ok" if failed == 0 else "warning",
        },
        "results": results,
        "notice": "approved_patches.json에 승인된 패치가 있으면 filter_dictionary/classification_overrides에 반영합니다."
    }
    write_json(STATUS_FILE, payload)
    write_json(ANALYSIS_STATUS_FILE, payload)
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
