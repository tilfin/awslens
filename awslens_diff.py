#!/usr/bin/env python3
"""Diff two awslens YAML snapshots and report changes."""

import argparse
import sys
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Identity key resolution
# ---------------------------------------------------------------------------

# Maps a list-key (e.g. "functions", "buckets") to the field used as identity.
_IDENTITY_KEYS: dict[str, str] = {
    "distributions": "id",
    "buckets": "name",
    "functions": "name",
    "clusters": "name",
    "repositories": "name",
    "services": "name",
    "vpcs": "id",
    "security_groups": "id",
    "load_balancers": "name",
    "hosted_zones": "id",
    "certificates": "arn",
    "rest_apis": "id",
    "http_apis": "id",
    "topics": "name",
    "queues": "name",
    "rules": "name",
    "tables": "name",
    "instances": "id",
    "alarms": "name",
    "custom_metrics": "namespace",
    "state_machines": "name",
    "secrets": "name",
    "iam_dependencies": "role",
    "stacks": "stack_name",
}


def _identity_key_for(list_key: str) -> str:
    return _IDENTITY_KEYS.get(list_key, "name")


def _item_identity(item: dict, id_key: str) -> str:
    return str(item.get(id_key, item.get("name", item.get("id", str(item)))))


# ---------------------------------------------------------------------------
# Deep diff
# ---------------------------------------------------------------------------

def _deep_diff(old, new, path: str = "") -> list[str]:
    """Return human-readable lines describing differences between old and new."""
    if old == new:
        return []
    if type(old) is not type(new):
        return [f"  {path}: {_summarize(old)} -> {_summarize(new)}"]
    if isinstance(old, dict):
        return _diff_dicts(old, new, path)
    if isinstance(old, list):
        return _diff_lists(old, new, path)
    return [f"  {path}: {_summarize(old)} -> {_summarize(new)}"]


def _diff_dicts(old: dict, new: dict, path: str) -> list[str]:
    lines: list[str] = []
    all_keys = dict.fromkeys(list(old.keys()) + list(new.keys()))
    for k in all_keys:
        child_path = f"{path}.{k}" if path else k
        if k not in old:
            lines.append(f"  + {child_path}: {_summarize(new[k])}")
        elif k not in new:
            lines.append(f"  - {child_path}: {_summarize(old[k])}")
        else:
            lines.extend(_deep_diff(old[k], new[k], child_path))
    return lines


def _diff_lists(old: list, new: list, path: str) -> list[str]:
    if old == new:
        return []
    # For short scalar lists, show inline
    if all(not isinstance(x, (dict, list)) for x in old + new):
        return [f"  {path}: {old} -> {new}"]
    # Fall back to index-based comparison
    lines: list[str] = []
    for i in range(max(len(old), len(new))):
        child_path = f"{path}[{i}]"
        if i >= len(old):
            lines.append(f"  + {child_path}: {_summarize(new[i])}")
        elif i >= len(new):
            lines.append(f"  - {child_path}: {_summarize(old[i])}")
        else:
            lines.extend(_deep_diff(old[i], new[i], child_path))
    return lines


def _summarize(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value if len(value) <= 80 else value[:77] + "..."
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        name = value.get("name") or value.get("id") or value.get("arn")
        if name:
            return f"{{{name}, ...}}"
        return f"{{{len(value)} keys}}"
    return str(value)[:80]


# ---------------------------------------------------------------------------
# Section-level diff
# ---------------------------------------------------------------------------

def _diff_resource_list(old_items: list[dict], new_items: list[dict], id_key: str) -> list[str]:
    old_map = {_item_identity(item, id_key): item for item in old_items}
    new_map = {_item_identity(item, id_key): item for item in new_items}
    old_ids = list(old_map.keys())
    new_ids = list(new_map.keys())
    lines: list[str] = []
    for rid in new_ids:
        if rid not in old_map:
            lines.append(f"  + {rid}")
    for rid in old_ids:
        if rid not in new_map:
            lines.append(f"  - {rid}")
    for rid in new_ids:
        if rid in old_map:
            changes = _deep_diff(old_map[rid], new_map[rid])
            if changes:
                lines.append(f"  ~ {rid}")
                lines.extend(f"    {line.strip()}" for line in changes)
    return lines


def _diff_section(section_key: str, old_data: dict, new_data: dict) -> list[str]:
    lines: list[str] = []
    all_list_keys = dict.fromkeys(list(old_data.keys()) + list(new_data.keys()))
    for list_key in all_list_keys:
        old_items = old_data.get(list_key, [])
        new_items = new_data.get(list_key, [])
        if not isinstance(old_items, list) or not isinstance(new_items, list):
            if old_items != new_items:
                lines.extend(_deep_diff(old_items, new_items, list_key))
            continue
        id_key = _identity_key_for(list_key)
        changes = _diff_resource_list(old_items, new_items, id_key)
        if changes:
            lines.extend(changes)
    return lines


# ---------------------------------------------------------------------------
# Top-level diff
# ---------------------------------------------------------------------------

def diff_yaml_files(old_doc: dict, new_doc: dict) -> list[str]:
    all_keys = dict.fromkeys(list(old_doc.keys()) + list(new_doc.keys()))
    output: list[str] = []
    for key in all_keys:
        if key == "metadata":
            continue
        if key not in old_doc:
            output.append(f"[+] {key} (new section)")
            _append_section_summary(output, new_doc[key], prefix="  + ")
            continue
        if key not in new_doc:
            output.append(f"[-] {key} (removed section)")
            _append_section_summary(output, old_doc[key], prefix="  - ")
            continue
        changes = _diff_section(key, old_doc[key], new_doc[key])
        if changes:
            output.append(f"[~] {key}")
            output.extend(changes)
    return output


def _append_section_summary(output: list[str], data: dict, prefix: str) -> None:
    for list_key, items in data.items():
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("id") or item.get("arn") or str(item)[:60]
                    output.append(f"{prefix}{name}")
                else:
                    output.append(f"{prefix}{item}")


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_diff_text(old_path: str, new_path: str, old_doc: dict, new_doc: dict, lines: list[str]) -> str:
    old_meta = old_doc.get("metadata", {})
    new_meta = new_doc.get("metadata", {})
    parts: list[str] = []
    parts.append(f"--- {old_path}  ({old_meta.get('generated', '?')})")
    parts.append(f"+++ {new_path}  ({new_meta.get('generated', '?')})")
    parts.append("")
    if not lines:
        parts.append("No differences found.")
    else:
        parts.extend(lines)
    parts.append("")
    return "\n".join(parts)


def format_diff_yaml(old_doc: dict, new_doc: dict) -> str:
    all_keys = dict.fromkeys(list(old_doc.keys()) + list(new_doc.keys()))
    result: dict = {"metadata": {"old": old_doc.get("metadata"), "new": new_doc.get("metadata")}}
    for key in all_keys:
        if key == "metadata":
            continue
        old_data = old_doc.get(key)
        new_data = new_doc.get(key)
        if old_data is None:
            result[key] = {"status": "added", "data": new_data}
        elif new_data is None:
            result[key] = {"status": "removed", "data": old_data}
        else:
            changes = _diff_section(key, old_data, new_data)
            if changes:
                result[key] = {"status": "changed", "old": old_data, "new": new_data}
    return yaml.dump(result, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diff two awslens YAML snapshots.",
    )
    parser.add_argument("old", help="Path to the older YAML file")
    parser.add_argument("new", help="Path to the newer YAML file")
    parser.add_argument("--format", choices=["text", "yaml"], default="text",
                        help="Output format (default: text)")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    args = parser.parse_args()

    old_doc = yaml.safe_load(Path(args.old).read_text())
    new_doc = yaml.safe_load(Path(args.new).read_text())
    if not isinstance(old_doc, dict) or not isinstance(new_doc, dict):
        print("Error: Both files must be valid YAML documents (top-level dict).", file=sys.stderr)
        sys.exit(1)

    diff_lines = diff_yaml_files(old_doc, new_doc)

    if args.format == "yaml":
        result = format_diff_yaml(old_doc, new_doc)
    else:
        result = format_diff_text(args.old, args.new, old_doc, new_doc, diff_lines)

    if args.output:
        Path(args.output).write_text(result)
    else:
        print(result, end="" if result.endswith("\n") else "\n")


if __name__ == "__main__":
    main()
