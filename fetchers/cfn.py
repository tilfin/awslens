"""CloudFormation stack info fetcher."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import log_warn
from core.output import Section


def fetch_cfn_stacks(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    cfn = ctx.client("cloudformation")
    stacks = _describe_stacks(cfn, ctx.stack_names or None)
    if not stacks:
        return []
    result = [_build_stack_info(cfn, s) for s in stacks]
    return [Section("CloudFormation Stacks", {"stacks": result})]


def _describe_stacks(cfn, stack_names: list[str] | None) -> list[dict]:
    stacks = []
    if stack_names:
        for name in stack_names:
            try:
                resp = cfn.describe_stacks(StackName=name)
                stacks.extend(resp.get("Stacks", []))
            except (ClientError, BotoCoreError) as e:
                log_warn(f"Could not describe stack {name}: {e}")
    else:
        try:
            paginator = cfn.get_paginator("describe_stacks")
            for page in paginator.paginate():
                stacks.extend(page.get("Stacks", []))
        except (ClientError, BotoCoreError) as e:
            log_warn(f"Could not list stacks: {e}")
    return stacks


def _build_stack_info(cfn, stack: dict) -> dict:
    stack_name = stack["StackName"]
    info = {
        "stack_name": stack_name,
        "status": stack.get("StackStatus"),
        "description": stack.get("Description"),
        "creation_time": str(stack.get("CreationTime", "")),
        "last_updated_time": str(stack.get("LastUpdatedTime", "")) if stack.get("LastUpdatedTime") else None,
    }
    params = stack.get("Parameters", [])
    if params:
        info["parameters"] = [
            {"key": p["ParameterKey"], "value": p.get("ParameterValue", ""), "resolved": p.get("ResolvedValue")}
            for p in params
        ]
    outputs = stack.get("Outputs", [])
    if outputs:
        info["outputs"] = [
            {"key": o["OutputKey"], "value": o.get("OutputValue", ""), "description": o.get("Description")}
            for o in outputs
        ]
    try:
        paginator = cfn.get_paginator("list_stack_resources")
        resources = []
        type_counts: dict[str, int] = {}
        for page in paginator.paginate(StackName=stack_name):
            for r in page.get("StackResourceSummaries", []):
                rtype = r["ResourceType"]
                type_counts[rtype] = type_counts.get(rtype, 0) + 1
                resources.append({
                    "logical_id": r["LogicalResourceId"],
                    "physical_id": r.get("PhysicalResourceId"),
                    "type": rtype,
                    "status": r.get("ResourceStatus"),
                })
        info["resources"] = resources
        info["resource_summary"] = [
            {"type": t, "count": c} for t, c in sorted(type_counts.items())
        ]
    except (ClientError, BotoCoreError) as e:
        log_warn(f"Could not list resources for stack {stack_name}: {e}")
    return info
