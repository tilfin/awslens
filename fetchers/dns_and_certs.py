"""Route53, ACM fetchers."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_route53(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("route53"):
        return []
    r53 = ctx.client("route53")
    resp = safe_call("Route53 hosted zones", r53.list_hosted_zones)
    if not resp:
        return []
    zones = resp.get("HostedZones", [])
    if not zones:
        return []
    result = []
    for z in zones:
        zone_id = z["Id"].replace("/hostedzone/", "")
        base = {
            "id": z["Id"],
            "name": z["Name"],
            "private": z.get("Config", {}).get("PrivateZone", False),
            "record_count": z.get("ResourceRecordSetCount"),
        }
        records = []
        try:
            rr = r53.list_resource_record_sets(HostedZoneId=zone_id)
            for rec in rr.get("ResourceRecordSets", []):
                if rec["Type"] in ("NS", "SOA"):
                    continue
                alias = None
                at = rec.get("AliasTarget")
                if at:
                    alias = {"dns": at["DNSName"], "zone_id": at["HostedZoneId"]}
                records.append({
                    "name": rec["Name"],
                    "type": rec["Type"],
                    "alias": alias,
                    "values": [rr_val["Value"] for rr_val in rec.get("ResourceRecords", [])],
                    "ttl": rec.get("TTL"),
                })
        except (ClientError, BotoCoreError):
            pass
        base["records"] = records
        result.append(base)
    if not result:
        return []
    return [Section("Route53", {"hosted_zones": result})]


def fetch_acm(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("acm"):
        return []
    acm = ctx.client("acm")
    resp = safe_call("ACM certificates", acm.list_certificates)
    if not resp:
        return []
    certs = resp.get("CertificateSummaryList", [])
    if not certs:
        return []
    result = []
    for c in certs:
        arn = c["CertificateArn"]
        try:
            dr = acm.describe_certificate(CertificateArn=arn)
            cert = dr["Certificate"]
            result.append({
                "domain": cert["DomainName"],
                "arn": cert["CertificateArn"],
                "status": cert.get("Status"),
                "type": cert.get("Type"),
                "sans": cert.get("SubjectAlternativeNames", []),
                "in_use_by": cert.get("InUseBy", []),
            })
        except (ClientError, BotoCoreError):
            continue
    if not result:
        return []
    return [Section("ACM", {"certificates": result})]
