import pytest
from app.models.schema_diff import DiffSeverity
from app.services.schema_diff import classify_severity, diff_schemas, extract_schema


def test_nested_schema_extraction():
    data = {
        "id": 101,
        "name": "Stripe Customer",
        "active": True,
        "balance": 250.50,
        "meta": None,
        "tags": ["premium", "vip"],
        "nested": {
            "address": "123 Main St",
            "codes": [1, 2, 3]
        }
    }
    schema = extract_schema(data)
    assert schema == {
        "id": "int",
        "name": "str",
        "active": "bool",
        "balance": "float",
        "meta": "NoneType",
        "tags": ["str"],
        "nested": {
            "address": "str",
            "codes": ["int"]
        }
    }


def test_none_to_string_is_informational():
    """Stabilizes nullable transitions: NoneType <-> concrete type is INFORMATIONAL, not breaking."""
    old_data = {"description": None}
    new_data = {"description": "Now populated with string"}

    old_schema = extract_schema(old_data)
    new_schema = extract_schema(new_data)

    severity, diff = diff_schemas(old_schema, new_schema)
    assert severity == DiffSeverity.INFORMATIONAL
    assert bool(diff) is True


def test_string_to_int_is_breaking():
    """Concrete type change between two non-null types is BREAKING."""
    old_data = {"account_id": "acc_12345"}
    new_data = {"account_id": 12345}

    old_schema = extract_schema(old_data)
    new_schema = extract_schema(new_data)

    severity, diff = diff_schemas(old_schema, new_schema)
    assert severity == DiffSeverity.BREAKING


def test_list_to_dict_is_breaking():
    """Container type shift from list to dict is BREAKING."""
    old_data = {"items": ["item1", "item2"]}
    new_data = {"items": {"id": 1, "name": "item1"}}

    old_schema = extract_schema(old_data)
    new_schema = extract_schema(new_data)

    severity, diff = diff_schemas(old_schema, new_schema)
    assert severity == DiffSeverity.BREAKING


def test_dict_to_list_is_breaking():
    """Container type shift from dict to list is BREAKING."""
    old_data = {"data": {"id": 1}}
    new_data = {"data": [1, 2]}

    old_schema = extract_schema(old_data)
    new_schema = extract_schema(new_data)

    severity, diff = diff_schemas(old_schema, new_schema)
    assert severity == DiffSeverity.BREAKING


def test_dictionary_item_removed_is_breaking():
    """Removing an existing field from the response schema is BREAKING."""
    old_data = {"id": 1, "status": "succeeded", "currency": "usd"}
    new_data = {"id": 1, "status": "succeeded"}

    old_schema = extract_schema(old_data)
    new_schema = extract_schema(new_data)

    severity, diff = diff_schemas(old_schema, new_schema)
    assert severity == DiffSeverity.BREAKING


def test_dictionary_item_added_is_non_breaking():
    """Adding a new field is NON_BREAKING for standard REST consumers."""
    old_data = {"id": 1, "status": "succeeded"}
    new_data = {"id": 1, "status": "succeeded", "new_opt_field": "test"}

    old_schema = extract_schema(old_data)
    new_schema = extract_schema(new_data)

    severity, diff = diff_schemas(old_schema, new_schema)
    assert severity == DiffSeverity.NON_BREAKING


def test_identical_schemas_have_no_diff():
    data = {"id": 100, "name": "sample"}
    schema1 = extract_schema(data)
    schema2 = extract_schema(data)

    severity, diff = diff_schemas(schema1, schema2)
    assert severity == DiffSeverity.INFORMATIONAL
    assert diff == {}
