"""S3 bucket fetcher."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_s3(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("s3"):
        return []
    s3 = ctx.client("s3")
    resp = safe_call("S3 buckets", s3.list_buckets)
    if not resp:
        return []
    bucket_names = [b["Name"] for b in resp.get("Buckets", [])]
    if not bucket_names:
        return []
    buckets = []
    for name in bucket_names:
        if filt.enabled and not filt.matches(name, "s3"):
            continue
        website = None
        try:
            w = s3.get_bucket_website(Bucket=name)
            website = {
                "index": (w.get("IndexDocument") or {}).get("Suffix"),
                "error": (w.get("ErrorDocument") or {}).get("Key"),
            }
        except (ClientError, BotoCoreError):
            pass
        notifications = []
        try:
            n = s3.get_bucket_notification_configuration(Bucket=name)
            for lc in n.get("LambdaFunctionConfigurations", []):
                notifications.append({"type": "lambda", "arn": lc["LambdaFunctionArn"], "events": lc["Events"]})
            for qc in n.get("QueueConfigurations", []):
                notifications.append({"type": "sqs", "arn": qc["QueueArn"], "events": qc["Events"]})
            for tc in n.get("TopicConfigurations", []):
                notifications.append({"type": "sns", "arn": tc["TopicArn"], "events": tc["Events"]})
        except (ClientError, BotoCoreError):
            pass
        buckets.append({"name": name, "website": website, "notifications": notifications})
    if not buckets:
        return []
    return [Section("S3", {"buckets": buckets})]
