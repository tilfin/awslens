"""CloudFront distribution fetcher."""

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_cloudfront(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("cloudfront"):
        return []
    cf = ctx.client("cloudfront")
    resp = safe_call("CloudFront distributions", cf.list_distributions)
    if not resp:
        return []
    items = (resp.get("DistributionList") or {}).get("Items") or []
    if not items:
        return []
    distributions = []
    for d in items:
        if filt.enabled and not filt.matches(d["Id"], "cloudfront"):
            continue
        origins = []
        for o in (d.get("Origins") or {}).get("Items", []):
            otype = "s3" if o.get("S3OriginConfig") else ("custom" if o.get("CustomOriginConfig") else "other")
            origins.append({"id": o["Id"], "domain": o["DomainName"], "type": otype})
        behaviors = []
        for b in (d.get("CacheBehaviors") or {}).get("Items", []):
            behaviors.append({"path": b["PathPattern"], "origin": b["TargetOriginId"]})
        behaviors.append({"path": "default (*)", "origin": d["DefaultCacheBehavior"]["TargetOriginId"]})
        distributions.append({
            "id": d["Id"],
            "domain": d["DomainName"],
            "status": d["Status"],
            "aliases": (d.get("Aliases") or {}).get("Items", []),
            "origins": origins,
            "behaviors": behaviors,
            "web_acl_id": d.get("WebACLId") or None,
        })
    if not distributions:
        return []
    return [Section("CloudFront", {"distributions": distributions})]
