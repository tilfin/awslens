"""CloudWatch, Step Functions, Secrets Manager fetchers."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_cloudwatch(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("cloudwatch"):
        return []
    cw = ctx.client("cloudwatch")
    sections = []
    sections.extend(_fetch_cloudwatch_alarms(cw, filt))
    sections.extend(_fetch_cloudwatch_metrics(cw))
    return sections


def _fetch_cloudwatch_alarms(cw, filt: ResourceFilter) -> list[Section]:
    resp = safe_call("CloudWatch alarms", cw.describe_alarms)
    if not resp:
        return []
    alarms = resp.get("MetricAlarms", []) + resp.get("CompositeAlarms", [])
    if not alarms:
        return []
    if filt.enabled:
        alarms = [a for a in alarms if filt.matches(a.get("AlarmName", ""), "cloudwatch") or filt.matches(a.get("AlarmArn", ""), "cloudwatch")]
    if not alarms:
        return []
    result = []
    for a in alarms:
        info = {
            "name": a["AlarmName"],
            "arn": a.get("AlarmArn"),
            "state": a.get("StateValue"),
            "description": a.get("AlarmDescription"),
            "actions_enabled": a.get("ActionsEnabled"),
            "alarm_actions": a.get("AlarmActions", []),
            "ok_actions": a.get("OKActions", []),
        }
        if a.get("MetricName"):
            info["namespace"] = a.get("Namespace")
            info["metric_name"] = a.get("MetricName")
            info["statistic"] = a.get("Statistic") or a.get("ExtendedStatistic")
            info["period"] = a.get("Period")
            info["evaluation_periods"] = a.get("EvaluationPeriods")
            info["threshold"] = a.get("Threshold")
            info["comparison"] = a.get("ComparisonOperator")
            dims = a.get("Dimensions", [])
            if dims:
                info["dimensions"] = {d["Name"]: d["Value"] for d in dims}
        if a.get("AlarmRule"):
            info["alarm_rule"] = a["AlarmRule"]
        result.append(info)
    return [Section("CloudWatch Alarms", {"alarms": result})]


def _fetch_cloudwatch_metrics(cw) -> list[Section]:
    resp = safe_call("CloudWatch metrics", cw.list_metrics)
    if not resp:
        return []
    metrics = resp.get("Metrics", [])
    if not metrics:
        return []
    custom: dict[str, list] = {}
    for m in metrics:
        ns = m.get("Namespace", "")
        if ns.startswith("AWS/"):
            continue
        dims = {d["Name"]: d["Value"] for d in m.get("Dimensions", [])}
        custom.setdefault(ns, []).append({
            "metric_name": m["MetricName"],
            "dimensions": dims if dims else None,
        })
    if not custom:
        return []
    result = [
        {"namespace": ns, "metrics": entries}
        for ns, entries in sorted(custom.items())
    ]
    return [Section("CloudWatch Custom Metrics", {"custom_metrics": result})]


def fetch_stepfunctions(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("stepfunctions"):
        return []
    sfn = ctx.client("stepfunctions")
    resp = safe_call("Step Functions state machines", sfn.list_state_machines)
    if not resp:
        return []
    machines = resp.get("stateMachines", [])
    if not machines:
        return []
    if filt.enabled:
        machines = [m for m in machines if filt.matches(m.get("name", ""), "stepfunctions") or filt.matches(m.get("stateMachineArn", ""), "stepfunctions")]
    if not machines:
        return []
    result = [
        {
            "name": m["name"],
            "arn": m["stateMachineArn"],
            "type": m.get("type"),
            "creation_date": str(m.get("creationDate", "")),
        }
        for m in machines
    ]
    return [Section("Step Functions", {"state_machines": result})]


def fetch_secrets(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("secrets"):
        return []
    sm = ctx.client("secretsmanager")
    resp = safe_call("Secrets Manager secrets", sm.list_secrets)
    if not resp:
        return []
    secrets = resp.get("SecretList", [])
    if not secrets:
        return []
    if filt.enabled:
        secrets = [s for s in secrets if filt.matches(s.get("Name", ""), "secrets") or filt.matches(s.get("ARN", ""), "secrets")]
    if not secrets:
        return []
    result = [
        {
            "name": s["Name"],
            "arn": s.get("ARN"),
            "description": s.get("Description"),
            "rotation_enabled": s.get("RotationEnabled", False),
            "tags": [{"key": t["Key"], "value": t["Value"]} for t in s.get("Tags", [])],
        }
        for s in secrets
    ]
    return [Section("Secrets Manager", {"secrets": result})]
