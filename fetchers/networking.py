"""VPC, Security Group, ALB fetchers."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_vpc(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("vpc"):
        return []
    ec2 = ctx.client("ec2")
    resp = safe_call("VPCs", ec2.describe_vpcs)
    if not resp:
        return []
    vpcs = resp.get("Vpcs", [])
    if not vpcs:
        return []
    result = []
    for v in vpcs:
        vpc_id = v["VpcId"]
        if filt.enabled and not filt.matches(vpc_id, "vpc"):
            continue
        tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
        base = {
            "id": vpc_id,
            "cidr": v.get("CidrBlock"),
            "name": tags.get("Name"),
            "is_default": v.get("IsDefault"),
        }
        base["subnets"] = _fetch_subnets(ec2, vpc_id)
        base["internet_gateways"] = _fetch_internet_gateways(ec2, vpc_id)
        base["nat_gateways"] = _fetch_nat_gateways(ec2, vpc_id)
        base["vpc_endpoints"] = _fetch_vpc_endpoints(ec2, vpc_id)
        base["route_tables"] = _fetch_route_tables(ec2, vpc_id)
        result.append(base)
    if not result:
        return []
    return [Section("VPC", {"vpcs": result})]


def _fetch_subnets(ec2, vpc_id: str) -> list:
    try:
        sr = ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        return [
            {
                "id": s["SubnetId"],
                "cidr": s["CidrBlock"],
                "az": s["AvailabilityZone"],
                "name": next((t["Value"] for t in s.get("Tags", []) if t["Key"] == "Name"), None),
                "public": s.get("MapPublicIpOnLaunch"),
            }
            for s in sr.get("Subnets", [])
        ]
    except (ClientError, BotoCoreError):
        return []


def _fetch_internet_gateways(ec2, vpc_id: str) -> list:
    try:
        ir = ec2.describe_internet_gateways(Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}])
        return [ig["InternetGatewayId"] for ig in ir.get("InternetGateways", [])]
    except (ClientError, BotoCoreError):
        return []


def _fetch_nat_gateways(ec2, vpc_id: str) -> list:
    try:
        nr = ec2.describe_nat_gateways(Filter=[{"Name": "vpc-id", "Values": [vpc_id]}])
        return [
            {
                "id": ng["NatGatewayId"],
                "subnet": ng["SubnetId"],
                "public_ip": (ng.get("NatGatewayAddresses", [{}])[0]).get("PublicIp"),
            }
            for ng in nr.get("NatGateways", []) if ng.get("State") == "available"
        ]
    except (ClientError, BotoCoreError):
        return []


def _fetch_vpc_endpoints(ec2, vpc_id: str) -> list:
    try:
        er = ec2.describe_vpc_endpoints(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        return [
            {"id": ep["VpcEndpointId"], "service": ep["ServiceName"], "type": ep["VpcEndpointType"]}
            for ep in er.get("VpcEndpoints", [])
        ]
    except (ClientError, BotoCoreError):
        return []


def _fetch_route_tables(ec2, vpc_id: str) -> list:
    try:
        rtr = ec2.describe_route_tables(Filters=[{"Name": "vpc-id", "Values": [vpc_id]}])
        return [
            {
                "id": rt["RouteTableId"],
                "name": next((t["Value"] for t in rt.get("Tags", []) if t["Key"] == "Name"), None),
                "associations": [
                    {"subnet": a.get("SubnetId"), "main": a.get("Main", False)}
                    for a in rt.get("Associations", [])
                ],
                "routes": [
                    {
                        "destination": r.get("DestinationCidrBlock") or r.get("DestinationIpv6CidrBlock") or r.get("DestinationPrefixListId"),
                        "target": r.get("GatewayId") or r.get("NatGatewayId") or r.get("TransitGatewayId") or r.get("VpcPeeringConnectionId") or r.get("NetworkInterfaceId") or "local",
                        "state": r.get("State"),
                    }
                    for r in rt.get("Routes", [])
                ],
            }
            for rt in rtr.get("RouteTables", [])
        ]
    except (ClientError, BotoCoreError):
        return []


def fetch_securitygroup(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("securitygroup"):
        return []
    ec2 = ctx.client("ec2")
    resp = safe_call("security groups", ec2.describe_security_groups)
    if not resp:
        return []
    sgs = resp.get("SecurityGroups", [])
    if not sgs:
        return []
    if filt.enabled:
        sgs = [sg for sg in sgs if filt.matches(sg["GroupId"], "securitygroup")]
    if not sgs:
        return []

    def parse_permissions(perms, dest_key="sources"):
        result = []
        for p in perms:
            sources = (
                [r["CidrIp"] for r in p.get("IpRanges", [])]
                + [r["CidrIpv6"] for r in p.get("Ipv6Ranges", [])]
                + [r["GroupId"] for r in p.get("UserIdGroupPairs", [])]
                + [r["PrefixListId"] for r in p.get("PrefixListIds", [])]
            )
            result.append({
                "protocol": p.get("IpProtocol"),
                "from_port": p.get("FromPort"),
                "to_port": p.get("ToPort"),
                dest_key: sources,
            })
        return result

    result = [
        {
            "id": sg["GroupId"],
            "name": sg["GroupName"],
            "description": sg.get("Description"),
            "vpc": sg.get("VpcId"),
            "ingress": parse_permissions(sg.get("IpPermissions", []), "sources"),
            "egress": parse_permissions(sg.get("IpPermissionsEgress", []), "destinations"),
        }
        for sg in sgs
    ]
    return [Section("Security Groups", {"security_groups": result})]


def fetch_alb(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("alb"):
        return []
    elb = ctx.client("elbv2")
    resp = safe_call("load balancers", elb.describe_load_balancers)
    if not resp:
        return []
    lbs = resp.get("LoadBalancers", [])
    if not lbs:
        return []
    result = []
    for lb in lbs:
        lb_arn = lb["LoadBalancerArn"]
        if filt.enabled and not filt.matches(lb_arn, "alb"):
            continue
        base = {
            "name": lb["LoadBalancerName"],
            "type": lb.get("Type"),
            "scheme": lb.get("Scheme"),
            "dns": lb.get("DNSName"),
            "vpc": lb.get("VpcId"),
            "subnets": [az["SubnetId"] for az in lb.get("AvailabilityZones", [])],
            "security_groups": lb.get("SecurityGroups", []),
        }
        listeners = _fetch_listeners(elb, lb_arn)
        tg_arns = list({l["target_group_arn"] for l in listeners if l.get("target_group_arn")})
        target_groups = _fetch_target_groups(elb, tg_arns)
        base["listeners"] = listeners
        base["target_groups"] = target_groups
        result.append(base)
    if not result:
        return []
    return [Section("Load Balancers", {"load_balancers": result})]


def _fetch_listeners(elb, lb_arn: str) -> list:
    try:
        lr = elb.describe_listeners(LoadBalancerArn=lb_arn)
        listeners = []
        for l in lr.get("Listeners", []):
            da = l.get("DefaultActions", [{}])[0]
            certs = l.get("Certificates", [])
            listeners.append({
                "port": l.get("Port"),
                "protocol": l.get("Protocol"),
                "default_action_type": da.get("Type"),
                "target_group_arn": da.get("TargetGroupArn"),
                "certificate_arn": certs[0]["CertificateArn"] if certs else None,
            })
        return listeners
    except (ClientError, BotoCoreError):
        return []


def _fetch_target_groups(elb, tg_arns: list[str]) -> list:
    target_groups = []
    for tg_arn in tg_arns:
        try:
            tgr = elb.describe_target_groups(TargetGroupArns=[tg_arn])
            tg = tgr["TargetGroups"][0]
            tg_info = {
                "name": tg["TargetGroupName"],
                "protocol": tg.get("Protocol"),
                "port": tg.get("Port"),
                "target_type": tg.get("TargetType"),
                "vpc": tg.get("VpcId"),
            }
            thr = elb.describe_target_health(TargetGroupArn=tg_arn)
            tg_info["targets"] = [
                {"id": t["Target"]["Id"], "port": t["Target"].get("Port"), "health": t["TargetHealth"]["State"]}
                for t in thr.get("TargetHealthDescriptions", [])
            ]
            target_groups.append(tg_info)
        except (ClientError, BotoCoreError):
            target_groups.append({"name": "unknown"})
    return target_groups
