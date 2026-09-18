"""Project native JSON Schemas onto Pond's discovery requirements.

References and union constraints remain intact. Pond discovery requires a direct type
on properties/items but preserves $defs and composition keywords. Public optional
nullable fields advertise omission instead of null; native validation is unchanged.
"""

import copy

TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})


def _types(node, definitions, seen=frozenset()):
    if "type" in node:
        value = node["type"]
        if not isinstance(value, str) or value not in TYPES:
            raise ValueError("Pond schema requires a supported scalar type name.")
        return {value}
    if "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/$defs/") or ref in seen:
            raise ValueError(f"Cannot resolve Pond schema type for reference {ref}.")
        name = ref.removeprefix("#/$defs/")
        if name not in definitions:
            raise ValueError(f"Missing Pond schema type definition {name}.")
        return _types(definitions[name], definitions, seen | {ref})
    for keyword in ("oneOf", "anyOf"):
        if keyword in node:
            return set().union(*(_types(branch, definitions, seen) for branch in node[keyword]))
    raise ValueError("Cannot infer an explicit Pond schema type.")


def pond_schema(schema):
    """Return a discovery schema without modifying native runtime constraints."""
    result = copy.deepcopy(schema)
    definitions = result.get("$defs", {})

    def adapt(node, label, *, required=True, root=False):
        types = _types(node, definitions)
        non_null = types - {"null"}
        if len(non_null) != 1:
            raise ValueError(f"Pond schema type is ambiguous for {label}.")
        if "null" in types and required:
            raise ValueError(f"Required nullable Pond schema type is unsupported for {label}.")
        node["type"] = next(iter(non_null))
        if not root and not node.get("description", "").strip():
            node["description"] = f"Input for {label}."
        if "null" in types:
            if node.get("default") is None:
                node.pop("default", None)
            for keyword in ("oneOf", "anyOf"):
                if keyword in node:
                    node[keyword] = [b for b in node[keyword] if b.get("type") != "null"]
            node["description"] += " Omit this field when unset; do not send null."
        for name, child in node.get("properties", {}).items():
            adapt(child, name, required=name in node.get("required", []))
        if "items" in node:
            node["items"].setdefault("description", f"One item in {label}.")
            adapt(node["items"], f"{label} item")

    adapt(result, "parameters", root=True)
    return result
