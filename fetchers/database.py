"""RDS, DynamoDB fetchers."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_rds(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("rds"):
        return []
    sections = []
    sections.extend(_fetch_rds_clusters(ctx, filt))
    sections.extend(_fetch_rds_instances(ctx, filt))
    return sections


def _fetch_rds_clusters(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    rds = ctx.client("rds")
    resp = safe_call("RDS clusters", rds.describe_db_clusters)
    if not resp:
        return []
    clusters = resp.get("DBClusters", [])
    if not clusters:
        return []
    result = []
    for c in clusters:
        result.append({
            "id": c["DBClusterIdentifier"],
            "engine": c.get("Engine"),
            "engine_version": c.get("EngineVersion"),
            "status": c.get("Status"),
            "endpoint": c.get("Endpoint"),
            "reader_endpoint": c.get("ReaderEndpoint"),
            "port": c.get("Port"),
            "vpc": c.get("DBSubnetGroup"),
            "security_groups": [sg["VpcSecurityGroupId"] for sg in c.get("VpcSecurityGroups", [])],
            "members": [
                {"id": m["DBInstanceIdentifier"], "is_writer": m["IsClusterWriter"]}
                for m in c.get("DBClusterMembers", [])
            ],
        })
    if not result:
        return []
    return [Section("RDS Clusters", {"clusters": result})]


def _fetch_rds_instances(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    rds = ctx.client("rds")
    resp = safe_call("RDS instances", rds.describe_db_instances)
    if not resp:
        return []
    instances = [i for i in resp.get("DBInstances", []) if not i.get("DBClusterIdentifier")]
    if not instances:
        return []
    result = []
    for i in instances:
        ep = i.get("Endpoint") or {}
        result.append({
            "id": i["DBInstanceIdentifier"],
            "engine": i.get("Engine"),
            "engine_version": i.get("EngineVersion"),
            "class": i.get("DBInstanceClass"),
            "status": i.get("DBInstanceStatus"),
            "endpoint": ep.get("Address"),
            "port": ep.get("Port"),
            "multi_az": i.get("MultiAZ"),
            "vpc": (i.get("DBSubnetGroup") or {}).get("VpcId"),
            "security_groups": [sg["VpcSecurityGroupId"] for sg in i.get("VpcSecurityGroups", [])],
            "storage": {"type": i.get("StorageType"), "size_gb": i.get("AllocatedStorage")},
        })
    if not result:
        return []
    return [Section("RDS Instances (standalone)", {"instances": result})]


def fetch_dynamodb(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("dynamodb"):
        return []
    ddb = ctx.client("dynamodb")
    resp = safe_call("DynamoDB tables", ddb.list_tables)
    if not resp:
        return []
    tables = resp.get("TableNames", [])
    if not tables:
        return []
    result = []
    for table in tables:
        if filt.enabled and not filt.matches(table, "dynamodb"):
            continue
        try:
            tr = ddb.describe_table(TableName=table)
            t = tr["Table"]
            stream = None
            ss = t.get("StreamSpecification")
            if ss:
                stream = {"enabled": ss.get("StreamEnabled"), "view_type": ss.get("StreamViewType")}
            result.append({
                "name": t["TableName"],
                "arn": t.get("TableArn"),
                "status": t.get("TableStatus"),
                "key_schema": [
                    {"attribute": k["AttributeName"], "type": k["KeyType"]}
                    for k in t.get("KeySchema", [])
                ],
                "gsi": [
                    {
                        "name": g["IndexName"],
                        "key_schema": [{"attribute": k["AttributeName"], "type": k["KeyType"]} for k in g.get("KeySchema", [])],
                        "projection": (g.get("Projection") or {}).get("ProjectionType"),
                    }
                    for g in t.get("GlobalSecondaryIndexes", [])
                ],
                "stream": stream,
                "billing": (t.get("BillingModeSummary") or {}).get("BillingMode", "PROVISIONED"),
            })
        except (ClientError, BotoCoreError):
            result.append({"name": table, "error": "could not describe"})
    if not result:
        return []
    return [Section("DynamoDB", {"tables": result})]
