import json
from typing import Any, Dict, Tuple
from deepdiff import DeepDiff

from app.models.schema_diff import DiffSeverity


def extract_schema(obj: Any) -> Any:
    """Recursively extracts structural schema (field names, types, nesting) from a JSON object.
    
    Values are discarded, retaining only type signatures.
    """
    if isinstance(obj, dict):
        return {k: extract_schema(v) for k, v in sorted(obj.items())}
    elif isinstance(obj, list):
        return [extract_schema(obj[0])] if obj else []
    elif obj is None:
        return "NoneType"
    else:
        return type(obj).__name__


def classify_severity(diff: DeepDiff) -> DiffSeverity:
    """Classifies a DeepDiff result into BREAKING, NON_BREAKING, or INFORMATIONAL.
    
    Rules:
    - dictionary_item_removed / iterable_item_removed -> BREAKING
    - Container type shifts (list <-> dict, container <-> primitive) -> BREAKING
    - Concrete type changes (e.g. str <-> int) -> BREAKING
    - Nullable transitions (NoneType <-> concrete type) -> INFORMATIONAL (prevents alert fatigue on optional fields)
    - dictionary_item_added / iterable_item_added -> NON_BREAKING
      (Assumption: standard JSON consumers ignore unknown fields; note that consumers with strict
       deserializers like strict protobuf may consider added required fields breaking).
    """
    if not diff:
        return DiffSeverity.INFORMATIONAL

    has_breaking = False
    has_non_breaking = False
    has_informational = False

    # 1. Removed fields / items
    if "dictionary_item_removed" in diff or "iterable_item_removed" in diff:
        has_breaking = True

    # 2. Container type shifts reported as type_changes by DeepDiff
    if "type_changes" in diff:
        for path, change in diff["type_changes"].items():
            old_type = change.get("old_type")
            new_type = change.get("new_type")
            old_type_name = getattr(old_type, "__name__", str(old_type))
            new_type_name = getattr(new_type, "__name__", str(new_type))

            # Check if one is NoneType and the other is concrete
            is_old_none = old_type_name in ("NoneType", "None") or change.get("old_value") == "NoneType"
            is_new_none = new_type_name in ("NoneType", "None") or change.get("new_value") == "NoneType"

            if (is_old_none and not is_new_none) or (is_new_none and not is_old_none):
                has_informational = True
            else:
                # Container shifts (list <-> dict) or primitive type shifts (str <-> int)
                has_breaking = True

    # 3. Leaf type shifts reported as values_changed
    # (Since extract_schema returns type names as string leaf values like 'str', 'int', 'NoneType')
    if "values_changed" in diff:
        for path, change in diff["values_changed"].items():
            old_val = str(change.get("old_value"))
            new_val = str(change.get("new_value"))

            if old_val == new_val:
                continue

            # Nullable stabilization
            if old_val == "NoneType" or new_val == "NoneType":
                has_informational = True
            else:
                # Concrete type shift e.g. 'str' -> 'int'
                has_breaking = True

    # 4. Added fields
    # Documented assumption: Non-breaking for standard REST clients that ignore unrecognized keys
    if "dictionary_item_added" in diff or "iterable_item_added" in diff:
        has_non_breaking = True

    if has_breaking:
        return DiffSeverity.BREAKING
    if has_non_breaking:
        return DiffSeverity.NON_BREAKING
    return DiffSeverity.INFORMATIONAL


def diff_schemas(old_schema: Any, new_schema: Any) -> Tuple[DiffSeverity, Dict[str, Any]]:
    """Compares two structural schemas and returns the classified severity and serialized diff summary."""
    if old_schema is None and new_schema is not None:
        return DiffSeverity.INFORMATIONAL, {"initial_snapshot": True}

    diff = DeepDiff(old_schema, new_schema, ignore_order=True)
    severity = classify_severity(diff)
    
    # Convert DeepDiff to JSON-serializable dictionary
    diff_summary = json.loads(diff.to_json()) if diff else {}
    return severity, diff_summary
