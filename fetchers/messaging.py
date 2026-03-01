"""SNS, SQS, EventBridge fetchers."""

import json

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_sns(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("sns"):
        return []
    sns = ctx.client("sns")
    resp = safe_call("SNS topics", sns.list_topics)
    if not resp:
        return []
    topics = resp.get("Topics", [])
    if not topics:
        return []
    result = []
    for t in topics:
        arn = t["TopicArn"]
        if filt.enabled and not filt.matches(arn, "sns"):
            continue
        name = arn.rsplit(":", 1)[-1]
        subs = []
        try:
            sr = sns.list_subscriptions_by_topic(TopicArn=arn)
            for s in sr.get("Subscriptions", []):
                subs.append({"protocol": s["Protocol"], "endpoint": s["Endpoint"]})
        except (ClientError, BotoCoreError):
            pass
        result.append({"name": name, "arn": arn, "subscriptions": subs})
    if not result:
        return []
    return [Section("SNS", {"topics": result})]


def fetch_sqs(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("sqs"):
        return []
    sqs = ctx.client("sqs")
    resp = safe_call("SQS queues", sqs.list_queues)
    if not resp:
        return []
    urls = resp.get("QueueUrls", [])
    if not urls:
        return []
    result = []
    for url in urls:
        if filt.enabled and not filt.matches(url, "sqs"):
            continue
        name = url.rsplit("/", 1)[-1]
        info = {"name": name, "url": url}
        try:
            ar = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])
            attrs = ar.get("Attributes", {})
            info["arn"] = attrs.get("QueueArn")
            info["type"] = "fifo" if attrs.get("FifoQueue") == "true" else "standard"
            info["visibility_timeout"] = attrs.get("VisibilityTimeout")
            info["delay_seconds"] = attrs.get("DelaySeconds")
            rp = attrs.get("RedrivePolicy")
            if rp:
                rpd = json.loads(rp)
                info["dlq"] = {
                    "target_arn": rpd.get("deadLetterTargetArn"),
                    "max_receive_count": rpd.get("maxReceiveCount"),
                }
            else:
                info["dlq"] = None
        except (ClientError, BotoCoreError):
            pass
        result.append(info)
    if not result:
        return []
    return [Section("SQS", {"queues": result})]


def fetch_eventbridge(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("eventbridge"):
        return []
    eb = ctx.client("events")
    resp = safe_call("EventBridge rules", eb.list_rules)
    if not resp:
        return []
    rules = resp.get("Rules", [])
    if not rules:
        return []
    result = []
    for r in rules:
        name = r["Name"]
        if filt.enabled and not filt.matches(name, "eventbridge"):
            continue
        info = {
            "name": name,
            "state": r.get("State"),
            "schedule": r.get("ScheduleExpression"),
            "event_pattern": r.get("EventPattern"),
            "event_bus": r.get("EventBusName", "default"),
        }
        targets = []
        try:
            tr = eb.list_targets_by_rule(Rule=name)
            targets = [{"id": t["Id"], "arn": t["Arn"]} for t in tr.get("Targets", [])]
        except (ClientError, BotoCoreError):
            pass
        info["targets"] = targets
        result.append(info)
    if not result:
        return []
    return [Section("EventBridge", {"rules": result})]
