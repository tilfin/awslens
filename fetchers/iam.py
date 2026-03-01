"""IAM dependency analysis fetcher."""

import json

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import log_progress, log_warn, safe_call
from core.output import Section

_ARN_SERVICE_MAP = {
    "s3": "s3", "dynamodb": "dynamodb", "sqs": "sqs", "sns": "sns",
    "lambda": "lambda", "states": "stepfunctions", "events": "eventbridge",
    "secretsmanager": "secrets", "kinesis": "kinesis", "kms": "kms",
    "logs": "cloudwatch_logs", "execute-api": "apigateway",
    "elasticloadbalancing": "alb", "rds": "rds", "es": "elasticsearch",
    "elasticache": "elasticache", "ecr": "ecr", "ecs": "ecs",
    "ssm": "ssm", "bedrock": "bedrock",
}


def fetch_iam_dependencies(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    log_progress("Collecting role ARNs from ECS task definitions...")
    ecs_roles = _collect_role_arns_from_ecs(ctx, filt)
    log_progress(f"Found {len(ecs_roles)} ECS task role(s)")

    log_progress("Collecting role ARNs from EC2 instance profiles...")
    ec2_roles = _collect_role_arns_from_ec2(ctx, filt)
    log_progress(f"Found {len(ec2_roles)} EC2 instance profile role(s)")

    all_roles = ecs_roles + ec2_roles
    if not all_roles:
        return []

    result = []
    for role_info in all_roles:
        role_name = role_info["role_arn"].rsplit("/", 1)[-1]
        log_progress(f"Analyzing policies for role: {role_name}...")
        allowed_actions = _analyze_role_policies(ctx, role_name)
        if not allowed_actions:
            continue
        result.append({
            "role": role_name,
            "source": role_info["source"],
            "allowed_actions": allowed_actions,
        })

    if not result:
        return []
    return [Section("IAM Dependencies", {"iam_dependencies": result})]


def _collect_role_arns_from_ecs(ctx: AWSContext, filt: ResourceFilter) -> list[dict]:
    ecs = ctx.client("ecs")
    results: list[dict] = []
    seen_roles: set[str] = set()

    resp = safe_call("ECS clusters", ecs.list_clusters)
    if not resp:
        return results

    for cluster_arn in resp.get("clusterArns", []):
        if filt.enabled and filt.has_ids("ecs") and not filt.matches(cluster_arn, "ecs"):
            continue
        cluster_name = cluster_arn.rsplit("/", 1)[-1]
        try:
            sr = ecs.list_services(cluster=cluster_arn)
            svc_arns = sr.get("serviceArns", [])
            if not svc_arns:
                continue
            sd = ecs.describe_services(cluster=cluster_arn, services=svc_arns)
            for svc in sd.get("services", []):
                td_arn = svc.get("taskDefinition")
                if not td_arn:
                    continue
                try:
                    td_resp = ecs.describe_task_definition(taskDefinition=td_arn)
                    td = td_resp.get("taskDefinition", {})
                    task_role_arn = td.get("taskRoleArn")
                    if task_role_arn and task_role_arn not in seen_roles:
                        seen_roles.add(task_role_arn)
                        results.append({
                            "role_arn": task_role_arn,
                            "source": f"ecs/{cluster_name}/{svc['serviceName']}",
                        })
                except (ClientError, BotoCoreError) as e:
                    log_warn(f"Could not describe task definition {td_arn}: {e}")
        except (ClientError, BotoCoreError) as e:
            log_warn(f"Could not list ECS services for {cluster_name}: {e}")

    return results


def _collect_role_arns_from_ec2(ctx: AWSContext, filt: ResourceFilter) -> list[dict]:
    ec2 = ctx.client("ec2")
    iam = ctx.client("iam")
    results: list[dict] = []
    seen_roles: set[str] = set()

    resp = safe_call("EC2 instances", ec2.describe_instances)
    if not resp:
        return results

    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            instance_id = inst["InstanceId"]
            profile = inst.get("IamInstanceProfile")
            if not profile:
                continue
            profile_arn = profile.get("Arn", "")
            profile_name = profile_arn.rsplit("/", 1)[-1] if "/" in profile_arn else ""
            if not profile_name:
                continue
            try:
                ip_resp = iam.get_instance_profile(InstanceProfileName=profile_name)
                for role in ip_resp.get("InstanceProfile", {}).get("Roles", []):
                    role_arn = role["Arn"]
                    if role_arn not in seen_roles:
                        seen_roles.add(role_arn)
                        results.append({
                            "role_arn": role_arn,
                            "source": f"ec2/{instance_id}",
                        })
            except (ClientError, BotoCoreError) as e:
                log_warn(f"Could not get instance profile {profile_name}: {e}")

    return results


def _analyze_role_policies(ctx: AWSContext, role_name: str) -> dict[str, list[dict]]:
    iam = ctx.client("iam")
    merged: dict[str, list[dict]] = {}

    def merge_into(parsed: dict[str, list[dict]]) -> None:
        for svc, entries in parsed.items():
            merged.setdefault(svc, []).extend(entries)

    # Managed policies
    try:
        resp = iam.list_attached_role_policies(RoleName=role_name)
        for pol in resp.get("AttachedPolicies", []):
            pol_arn = pol["PolicyArn"]
            if pol_arn.startswith("arn:aws:iam::aws:"):
                continue
            try:
                pr = iam.get_policy(PolicyArn=pol_arn)
                version_id = pr["Policy"]["DefaultVersionId"]
                vr = iam.get_policy_version(PolicyArn=pol_arn, VersionId=version_id)
                doc = vr["PolicyVersion"]["Document"]
                if isinstance(doc, str):
                    doc = json.loads(doc)
                merge_into(_parse_policy_resources(doc))
            except (ClientError, BotoCoreError) as e:
                log_warn(f"Could not read policy {pol_arn}: {e}")
    except (ClientError, BotoCoreError) as e:
        log_warn(f"Could not list managed policies for {role_name}: {e}")

    # Inline policies
    try:
        resp = iam.list_role_policies(RoleName=role_name)
        for policy_name in resp.get("PolicyNames", []):
            try:
                pr = iam.get_role_policy(RoleName=role_name, PolicyName=policy_name)
                doc = pr["PolicyDocument"]
                if isinstance(doc, str):
                    doc = json.loads(doc)
                merge_into(_parse_policy_resources(doc))
            except (ClientError, BotoCoreError) as e:
                log_warn(f"Could not read inline policy {policy_name}: {e}")
    except (ClientError, BotoCoreError) as e:
        log_warn(f"Could not list inline policies for {role_name}: {e}")

    # Deduplicate
    deduped: dict[str, list[dict]] = {}
    for svc, entries in merged.items():
        all_actions: set[str] = set()
        all_resources: set[str] = set()
        for e in entries:
            all_actions.update(e["actions"])
            all_resources.update(e["resources"])
        deduped[svc] = [{
            "actions": sorted(all_actions),
            "resources": sorted(all_resources),
        }]
    return deduped


def _parse_policy_resources(document: dict) -> dict[str, list[dict]]:
    service_map: dict[str, dict[str, set]] = {}
    statements = document.get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]

    for stmt in statements:
        if stmt.get("Effect") != "Allow":
            continue
        actions = stmt.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        resources = stmt.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]

        action_by_svc: dict[str, list[str]] = {}
        for action in actions:
            if ":" not in action:
                continue
            svc = action.split(":")[0].lower()
            action_by_svc.setdefault(svc, []).append(action)

        for svc, svc_actions in action_by_svc.items():
            display_svc = _ARN_SERVICE_MAP.get(svc, svc)
            if display_svc not in service_map:
                service_map[display_svc] = {"actions": set(), "resources": set()}
            service_map[display_svc]["actions"].update(svc_actions)
            for res in resources:
                res_svc = _extract_service_from_arn(res)
                if res_svc == display_svc or res == "*":
                    service_map[display_svc]["resources"].add(
                        _extract_resource_name_from_arn(res)
                    )

    result: dict[str, list[dict]] = {}
    for svc, data in sorted(service_map.items()):
        result[svc] = [{
            "actions": sorted(data["actions"]),
            "resources": sorted(data["resources"]) if data["resources"] else ["*"],
        }]
    return result


def _extract_service_from_arn(arn: str) -> str | None:
    if arn == "*":
        return None
    parts = arn.split(":")
    if len(parts) < 3:
        return None
    return _ARN_SERVICE_MAP.get(parts[2])


def _extract_resource_name_from_arn(arn: str) -> str:
    if arn == "*":
        return "*"
    if arn.startswith("arn:aws:s3:::"):
        return arn[len("arn:aws:s3:::"):]
    parts = arn.split(":")
    if len(parts) >= 6:
        resource_part = ":".join(parts[5:])
        for sep in ["/", ":"]:
            if sep in resource_part:
                prefix = resource_part.split(sep, 1)[0]
                if prefix in (
                    "table", "function", "queue", "topic", "secret", "stateMachine",
                    "rule", "stream", "key", "log-group", "cluster", "service",
                    "task-definition", "repository",
                ):
                    return resource_part.split(sep, 1)[-1]
                return resource_part
        return resource_part
    return arn
