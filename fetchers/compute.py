"""Lambda, ECS, and ECR fetchers."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_lambda_svc(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("lambda"):
        return []
    lam = ctx.client("lambda")
    resp = safe_call("Lambda functions", lam.list_functions)
    if not resp:
        return []
    functions = resp.get("Functions", [])
    if not functions:
        return []
    result = []
    for f in functions:
        fname = f["FunctionName"]
        if filt.enabled and not filt.matches(fname, "lambda"):
            continue
        vpc_config = None
        vc = f.get("VpcConfig")
        if vc and vc.get("SubnetIds"):
            vpc_config = {"subnets": vc["SubnetIds"], "security_groups": vc.get("SecurityGroupIds", [])}
        info = {
            "name": fname,
            "runtime": f.get("Runtime", "container"),
            "handler": f.get("Handler"),
            "memory": f.get("MemorySize"),
            "timeout": f.get("Timeout"),
            "arn": f.get("FunctionArn"),
            "role": f.get("Role"),
            "vpc": vpc_config,
            "layers": [la["Arn"] for la in f.get("Layers", [])],
            "environment_vars": list((f.get("Environment") or {}).get("Variables", {}).keys()),
        }
        event_sources = []
        try:
            esr = lam.list_event_source_mappings(FunctionName=fname)
            for es in esr.get("EventSourceMappings", []):
                arn = es.get("EventSourceArn", "")
                parts = arn.split(":") if arn else []
                event_sources.append({
                    "type": parts[2] if len(parts) > 2 else "unknown",
                    "arn": arn,
                    "state": es.get("State"),
                })
        except (ClientError, BotoCoreError):
            pass
        info["event_sources"] = event_sources
        result.append(info)
    if not result:
        return []
    return [Section("Lambda", {"functions": result})]


def fetch_ecs(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("ecs"):
        return []
    ecs = ctx.client("ecs")
    clusters = _fetch_ecs_clusters(ecs, filt)
    task_definitions = _fetch_ecs_task_definitions(ecs, filt)
    if not clusters and not task_definitions:
        return []
    return [Section("ECS", {
        "clusters": clusters,
        "task_definitions": task_definitions,
    })]


def _fetch_ecs_clusters(ecs, filt: ResourceFilter) -> list[dict]:
    resp = safe_call("ECS clusters", ecs.list_clusters)
    if not resp:
        return []
    cluster_arns = resp.get("clusterArns", [])
    if not cluster_arns:
        return []
    result = []
    for cluster_arn in cluster_arns:
        if filt.enabled and not filt.matches(cluster_arn, "ecs"):
            continue
        try:
            cr = ecs.describe_clusters(clusters=[cluster_arn])
            c = cr["clusters"][0]
            info = {
                "name": c["clusterName"],
                "arn": c["clusterArn"],
                "status": c["status"],
                "running_tasks": c.get("runningTasksCount"),
                "active_services": c.get("activeServicesCount"),
            }
        except (ClientError, BotoCoreError):
            info = {"name": "unknown"}
        services_detail = []
        try:
            sr = ecs.list_services(cluster=cluster_arn)
            svc_arns = sr.get("serviceArns", [])
            if svc_arns:
                sd = ecs.describe_services(cluster=cluster_arn, services=svc_arns)
                for s in sd.get("services", []):
                    nc = (s.get("networkConfiguration") or {}).get("awsvpcConfiguration") or {}
                    services_detail.append({
                        "name": s["serviceName"],
                        "status": s.get("status"),
                        "desired": s.get("desiredCount"),
                        "running": s.get("runningCount"),
                        "launch_type": s.get("launchType", "FARGATE"),
                        "task_definition": s.get("taskDefinition"),
                        "target_groups": [
                            {"target_group_arn": lb.get("targetGroupArn"), "container": lb.get("containerName"), "port": lb.get("containerPort")}
                            for lb in s.get("loadBalancers", [])
                        ],
                        "subnets": nc.get("subnets", []),
                        "security_groups": nc.get("securityGroups", []),
                    })
        except (ClientError, BotoCoreError):
            pass
        info["services"] = services_detail
        result.append(info)
    if not result:
        return []
    return result


def _fetch_ecs_task_definitions(ecs, filt: ResourceFilter) -> list[dict]:
    """Collect active task definitions, omitting environment variable values."""
    task_definition_arns = []
    params = {"status": "ACTIVE", "sort": "DESC"}
    while True:
        resp = safe_call("ECS task definitions", ecs.list_task_definitions, **params)
        if not resp:
            break
        task_definition_arns.extend(resp.get("taskDefinitionArns", []))
        next_token = resp.get("nextToken")
        if not next_token:
            break
        params["nextToken"] = next_token

    result = []
    for arn in task_definition_arns:
        family_and_revision = arn.rsplit("/", 1)[-1]
        if filt.enabled and not (
            filt.matches(arn, "ecs")
            or filt.matches(family_and_revision, "ecs")
        ):
            continue
        try:
            resp = ecs.describe_task_definition(taskDefinition=arn)
        except (ClientError, BotoCoreError):
            continue
        definition = resp.get("taskDefinition", {})
        if definition:
            result.append(_summarize_task_definition(definition))
    return result


def _summarize_task_definition(definition: dict) -> dict:
    containers = []
    for container in definition.get("containerDefinitions", []):
        log_options = container.get("logConfiguration") or {}
        containers.append({
            "name": container.get("name"),
            "image": container.get("image"),
            "essential": container.get("essential", True),
            "cpu": container.get("cpu"),
            "memory": container.get("memory"),
            "memory_reservation": container.get("memoryReservation"),
            "port_mappings": [
                {
                    "name": port.get("name"),
                    "container_port": port.get("containerPort"),
                    "host_port": port.get("hostPort"),
                    "protocol": port.get("protocol"),
                    "app_protocol": port.get("appProtocol"),
                }
                for port in container.get("portMappings", [])
            ],
            "environment_vars": [item.get("name") for item in container.get("environment", [])],
            "secrets": [item.get("name") for item in container.get("secrets", [])],
            "log_configuration": {
                "driver": log_options.get("logDriver"),
                "options": log_options.get("options", {}),
            } if log_options else None,
        })
    runtime = definition.get("runtimePlatform") or {}
    return {
        "family": definition.get("family"),
        "revision": definition.get("revision"),
        "arn": definition.get("taskDefinitionArn"),
        "status": definition.get("status"),
        "requires_compatibilities": definition.get("requiresCompatibilities", []),
        "network_mode": definition.get("networkMode"),
        "cpu": definition.get("cpu"),
        "memory": definition.get("memory"),
        "task_role": definition.get("taskRoleArn"),
        "execution_role": definition.get("executionRoleArn"),
        "runtime_platform": {
            "cpu_architecture": runtime.get("cpuArchitecture"),
            "operating_system_family": runtime.get("operatingSystemFamily"),
        } if runtime else None,
        "ephemeral_storage_gib": (definition.get("ephemeralStorage") or {}).get("sizeInGiB"),
        "containers": containers,
        "volumes": [volume.get("name") for volume in definition.get("volumes", [])],
    }


def fetch_ecr(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("ecr"):
        return []
    ecr = ctx.client("ecr")
    resp = safe_call("ECR repositories", ecr.describe_repositories)
    if not resp:
        return []
    repos = resp.get("repositories", [])
    if not repos:
        return []
    if filt.enabled:
        repos = [r for r in repos if filt.matches(r.get("repositoryName", ""), "ecr") or filt.matches(r.get("repositoryArn", ""), "ecr")]
    if not repos:
        return []
    result = []
    for r in repos:
        repo_name = r["repositoryName"]
        info = {
            "name": repo_name,
            "arn": r.get("repositoryArn"),
            "uri": r.get("repositoryUri"),
            "image_tag_mutability": r.get("imageTagMutability"),
            "scan_on_push": (r.get("imageScanningConfiguration") or {}).get("scanOnPush", False),
            "encryption": (r.get("encryptionConfiguration") or {}).get("encryptionType"),
        }
        try:
            ecr.get_lifecycle_policy(repositoryName=repo_name)
            info["lifecycle_policy"] = True
        except (ClientError, BotoCoreError):
            info["lifecycle_policy"] = False
        try:
            ir = ecr.describe_images(
                repositoryName=repo_name,
                filter={"tagStatus": "TAGGED"},
                maxResults=5,
            )
            info["recent_images"] = [
                {
                    "tags": img.get("imageTags", []),
                    "pushed_at": str(img.get("imagePushedAt", "")),
                    "size_mb": round(img.get("imageSizeInBytes", 0) / 1024 / 1024, 1),
                }
                for img in sorted(
                    ir.get("imageDetails", []),
                    key=lambda x: x.get("imagePushedAt", ""),
                    reverse=True,
                )
            ]
        except (ClientError, BotoCoreError):
            info["recent_images"] = []
        result.append(info)
    if not result:
        return []
    return [Section("ECR", {"repositories": result})]
