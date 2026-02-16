"""Deep merge utilities for machine-specific config overrides."""

from __future__ import annotations

from typing import Any, Dict, List


def _is_named_object_list(lst: list) -> bool:
    """Check if all items in a list are dicts containing a 'name' key.

    Empty lists return False (treated as scalar lists).
    """
    if not lst:
        return False
    return all(isinstance(item, dict) and "name" in item for item in lst)


def _merge_named_lists(base: List[dict], override: List[dict]) -> List[dict]:
    """Merge two named-object lists by matching on the 'name' key.

    Items with matching names are deep-merged (override wins on conflict).
    New items from override are appended.
    Order: base items first (merged if matched), then new override items.
    """
    # Index base items by name, preserving order
    base_by_name = {item["name"]: item for item in base}
    seen_names = set()
    result = []

    # Merge or keep base items in order
    for item in base:
        name = item["name"]
        seen_names.add(name)
        # Find matching override
        override_item = next((o for o in override if o.get("name") == name), None)
        if override_item is not None:
            result.append(deep_merge(item, override_item))
        else:
            result.append(_deep_copy(item))

    # Append new items from override that weren't in base
    for item in override:
        if item.get("name") not in seen_names:
            result.append(_deep_copy(item))

    return result


def _deep_copy(obj: Any) -> Any:
    """Simple deep copy for JSON-compatible structures."""
    if isinstance(obj, dict):
        return {k: _deep_copy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_copy(item) for item in obj]
    return obj


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively deep-merge two dicts. Override wins on conflict.

    Merge rules:
    - Dicts: recursive deep merge
    - Lists of named objects (all items are dicts with 'name' key):
      merge by name, append new items
    - Other lists (scalars, strings, anonymous dicts): replace entirely
    - Scalars: override wins

    Returns a new dict (no mutation of inputs).
    """
    result = _deep_copy(base)

    for key, override_val in override.items():
        if key not in result:
            result[key] = _deep_copy(override_val)
            continue

        base_val = result[key]

        # Both dicts -> recursive merge
        if isinstance(base_val, dict) and isinstance(override_val, dict):
            result[key] = deep_merge(base_val, override_val)
        # Both lists -> check if named-object lists
        elif isinstance(base_val, list) and isinstance(override_val, list):
            if _is_named_object_list(base_val) and _is_named_object_list(override_val):
                result[key] = _merge_named_lists(base_val, override_val)
            else:
                # Scalar/anonymous lists: replace entirely
                result[key] = _deep_copy(override_val)
        else:
            # Scalar or type mismatch: override wins
            result[key] = _deep_copy(override_val)

    return result
