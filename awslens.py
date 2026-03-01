#!/usr/bin/env python3
"""Collect AWS resource snapshots as Markdown or YAML."""

import argparse
import sys

from core.context import AWSContext
from core.filter import ResourceFilter, expand_stack_patterns, resolve_stack_resources
from core.logging import log_progress, log_warn
from core.output import Section, build_header_info, format_markdown, format_yaml
from fetchers import ALL_SERVICES, SERVICE_FETCHERS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collect AWS resource snapshots as Markdown or YAML.",
    )
    parser.add_argument("--profile", default=None, help="AWS CLI profile name")
    parser.add_argument("--region", default=None, help="AWS region")
    parser.add_argument("--output", default=None, help="Output file path (default: stdout)")
    parser.add_argument("--services", default=None, help="Comma-separated services to fetch (default: all)")
    parser.add_argument("--stack", action="append", default=[], help="CloudFormation stack name (repeatable)")
    parser.add_argument("--format", choices=["markdown", "yaml"], default="markdown", help="Output format (default: markdown)")
    args = parser.parse_args()

    stack_names = expand_stack_patterns(
        AWSContext(args.profile, args.region), args.stack,
    ) if args.stack else []

    ctx = AWSContext(args.profile, args.region, stack_names=stack_names)
    filt = ResourceFilter()
    selected = args.services.split(",") if args.services else list(ALL_SERVICES)

    if stack_names:
        resolve_stack_resources(ctx, filt, stack_names)
        if filt.enabled:
            active = set(filt.active_services())
            derived_services = {"iam_dependencies", "cfn_stacks"}
            if selected == list(ALL_SERVICES):
                selected = sorted(active) + [s for s in ALL_SERVICES if s in derived_services and s not in active]
            else:
                selected = [s for s in selected if s in active or s in derived_services]

    all_sections: list[Section] = []
    total = len(selected)
    for idx, svc in enumerate(selected, 1):
        fetcher = SERVICE_FETCHERS.get(svc)
        if not fetcher:
            log_warn(f"Unknown service: {svc}, skipping")
            continue
        log_progress(f"[{idx}/{total}] Fetching {svc}...")
        try:
            sections = fetcher(ctx, filt)
            all_sections.extend(sections)
        except Exception as e:
            log_warn(f"Failed to fetch {svc}, skipping: {e}")

    log_progress("Done.")
    header = build_header_info(ctx)
    if args.format == "yaml":
        result = format_yaml(header, all_sections)
    else:
        result = format_markdown(header, all_sections)

    if args.output:
        with open(args.output, "w") as f:
            f.write(result)
        log_progress(f"Output written to {args.output}")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
