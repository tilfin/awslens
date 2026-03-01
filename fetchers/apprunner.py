"""App Runner fetcher."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_apprunner(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("apprunner"):
        return []
    ar = ctx.client("apprunner")
    resp = safe_call("App Runner services", ar.list_services)
    if not resp:
        return []
    summaries = resp.get("ServiceSummaryList", [])
    if not summaries:
        return []
    if filt.enabled:
        summaries = [
            s for s in summaries
            if filt.matches(s.get("ServiceName", ""), "apprunner")
            or filt.matches(s.get("ServiceArn", ""), "apprunner")
        ]
    if not summaries:
        return []
    result = []
    for s in summaries:
        service_arn = s["ServiceArn"]
        info = _describe_service(ar, service_arn)
        if info:
            _attach_custom_domains(ar, service_arn, info)
            result.append(info)
    if not result:
        return []
    return [Section("App Runner", {"services": result})]


def _describe_service(ar, service_arn: str) -> dict | None:
    try:
        resp = ar.describe_service(ServiceArn=service_arn)
    except (ClientError, BotoCoreError):
        return None
    svc = resp.get("Service", {})
    src = svc.get("SourceConfiguration", {})
    source = _parse_source(src)
    instance = svc.get("InstanceConfiguration", {})
    network = svc.get("NetworkConfiguration", {})
    health = svc.get("HealthCheckConfiguration", {})
    auto_scaling_arn = svc.get("AutoScalingConfigurationSummary", {}).get("AutoScalingConfigurationArn")
    return {
        "name": svc.get("ServiceName"),
        "arn": svc.get("ServiceArn"),
        "service_id": svc.get("ServiceId"),
        "url": svc.get("ServiceUrl"),
        "status": svc.get("Status"),
        "source": source,
        "instance": {
            "cpu": instance.get("Cpu"),
            "memory": instance.get("Memory"),
            "role": instance.get("InstanceRoleArn"),
        },
        "networking": _parse_network(network),
        "health_check": {
            "protocol": health.get("Protocol"),
            "path": health.get("Path"),
            "interval": health.get("Interval"),
            "timeout": health.get("Timeout"),
        } if health else None,
        "auto_scaling_arn": auto_scaling_arn,
        "observability": _parse_observability(svc),
    }


def _parse_source(src: dict) -> dict:
    if src.get("ImageRepository"):
        repo = src["ImageRepository"]
        return {
            "type": "image",
            "image_uri": repo.get("ImageIdentifier"),
            "repository_type": repo.get("ImageRepositoryType"),
            "port": (repo.get("ImageConfiguration") or {}).get("Port"),
        }
    if src.get("CodeRepository"):
        repo = src["CodeRepository"]
        return {
            "type": "code",
            "repository_url": repo.get("RepositoryUrl"),
            "branch": (repo.get("SourceCodeVersion") or {}).get("Value"),
        }
    if src.get("AuthenticationConfiguration", {}).get("ConnectionArn"):
        return {"type": "connection", "connection_arn": src["AuthenticationConfiguration"]["ConnectionArn"]}
    return {"type": "unknown"}


def _parse_network(network: dict) -> dict:
    egress = network.get("EgressConfiguration", {})
    ingress = network.get("IngressConfiguration", {})
    ip = network.get("IpAddressType")
    result = {"ip_address_type": ip}
    if egress.get("EgressType") == "VPC":
        result["egress_type"] = "VPC"
        result["vpc_connector_arn"] = egress.get("VpcConnectorArn")
    else:
        result["egress_type"] = "DEFAULT"
    result["is_publicly_accessible"] = ingress.get("IsPubliclyAccessible", True)
    return result


def _parse_observability(svc: dict) -> dict | None:
    obs = svc.get("ObservabilityConfiguration")
    if not obs or not obs.get("ObservabilityEnabled"):
        return None
    return {"enabled": True, "arn": obs.get("ObservabilityConfigurationArn")}


def _attach_custom_domains(ar, service_arn: str, info: dict) -> None:
    try:
        resp = ar.describe_custom_domains(ServiceArn=service_arn)
        domains = resp.get("CustomDomains", [])
        if domains:
            info["custom_domains"] = [
                {"domain": d.get("DomainName"), "status": d.get("Status")}
                for d in domains
            ]
    except (ClientError, BotoCoreError):
        pass
