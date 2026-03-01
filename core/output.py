"""Output formatting helpers."""

from datetime import datetime, timezone
from typing import NamedTuple

import yaml

from .context import AWSContext


class Section(NamedTuple):
    title: str
    data: dict


def build_header_info(ctx: AWSContext) -> dict:
    return {
        "profile": ctx.resolve_profile_display(),
        "region": ctx.resolve_region_display(),
        "stacks": ctx.stack_names if ctx.stack_names else None,
        "generated": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def format_markdown(header: dict, sections: list[Section]) -> str:
    lines = [f"# AWS Resources - {header['profile']} ({header['region']})"]
    if header.get("stacks"):
        lines.append(f"Stack: {', '.join(header['stacks'])}")
    lines.append(f"Generated: {header['generated']}")
    lines.append("")
    parts = ["\n".join(lines) + "\n"]
    for section in sections:
        parts.append(f"## {section.title}\n\n")
        text = yaml.dump(section.data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        parts.append(f"```yaml\n{text}```\n\n")
    return "".join(parts)


def format_yaml(header: dict, sections: list[Section]) -> str:
    doc: dict = {"metadata": header}
    for section in sections:
        key = section.title.lower().replace(" ", "_").replace("(", "").replace(")", "")
        if key in doc:
            key = f"{key}_2"
        doc[key] = section.data
    return yaml.dump(doc, default_flow_style=False, allow_unicode=True, sort_keys=False)
