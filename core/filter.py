"""CloudFormation stack-based resource filtering."""

import json
import re

from botocore.exceptions import ClientError, BotoCoreError

from .context import AWSContext
from .logging import log_progress, log_warn

CFN_TYPE_TO_SERVICE = {
    "AWS::CloudFront::Distribution": "cloudfront",
    "AWS::S3::Bucket": "s3",
    "AWS::ElasticLoadBalancingV2::LoadBalancer": "alb",
    "AWS::ElasticLoadBalancingV2::TargetGroup": "alb",
    "AWS::Lambda::Function": "lambda",
    "AWS::SNS::Topic": "sns",
    "AWS::SQS::Queue": "sqs",
    "AWS::ApiGateway::RestApi": "apigateway",
    "AWS::ApiGatewayV2::Api": "apigateway",
    "AWS::Route53::HostedZone": "route53",
    "AWS::CertificateManager::Certificate": "acm",
    "AWS::RDS::DBCluster": "rds",
    "AWS::RDS::DBInstance": "rds",
    "AWS::DynamoDB::Table": "dynamodb",
    "AWS::SecretsManager::Secret": "secrets",
    "AWS::EC2::VPC": "vpc",
    "AWS::EC2::Subnet": "vpc",
    "AWS::EC2::InternetGateway": "vpc",
    "AWS::EC2::NatGateway": "vpc",
    "AWS::EC2::VPCEndpoint": "vpc",
    "AWS::EC2::SecurityGroup": "securitygroup",
    "AWS::ECS::Cluster": "ecs",
    "AWS::ECS::Service": "ecs",
    "AWS::ECS::TaskDefinition": "ecs",
    "AWS::ECR::Repository": "ecr",
    "AWS::CloudWatch::Alarm": "cloudwatch",
    "AWS::Events::Rule": "eventbridge",
    "AWS::Scheduler::Schedule": "eventbridge",
    "AWS::StepFunctions::StateMachine": "stepfunctions",
    "AWS::AppRunner::Service": "apprunner",
}


class ResourceFilter:
    def __init__(self):
        self.enabled = False
        self._ids: dict[str, set[str]] = {}

    def add(self, service: str, physical_id: str) -> None:
        if not physical_id or physical_id == "null":
            return
        self._ids.setdefault(service, set()).add(physical_id)

    def classify_and_add(self, resource_type: str, physical_id: str) -> None:
        service = CFN_TYPE_TO_SERVICE.get(resource_type)
        if service:
            self.add(service, physical_id)

    def classify_output_value(self, value: str) -> None:
        _ARN_CLASSIFIERS = [
            ("arn:aws:lambda:", "lambda", lambda v: v.split(":function:")[-1].split(":")[0]),
            ("arn:aws:dynamodb:", "dynamodb", lambda v: v.rsplit("/", 1)[-1]),
            ("arn:aws:s3:::", "s3", lambda v: v[len("arn:aws:s3:::"):]),
            ("arn:aws:sqs:", "sqs", lambda v: v),
            ("arn:aws:sns:", "sns", lambda v: v.rsplit(":", 1)[-1]),
            ("arn:aws:secretsmanager:", "secrets", lambda v: v.split(":secret:")[-1]),
            ("arn:aws:states:", "stepfunctions", lambda v: v.split(":stateMachine:")[-1]),
            ("arn:aws:ecr:", "ecr", lambda v: v.rsplit("/", 1)[-1]),
            ("arn:aws:events:", "eventbridge", lambda v: v.rsplit("/", 1)[-1]),
            ("arn:aws:scheduler:", "eventbridge", lambda v: v.rsplit("/", 1)[-1]),
            ("arn:aws:apprunner:", "apprunner", lambda v: v.rsplit("/", 1)[-1]),
        ]
        for prefix, service, extractor in _ARN_CLASSIFIERS:
            if value.startswith(prefix):
                self.add(service, extractor(value))
                return

    def build(self) -> None:
        if self._ids:
            self.enabled = True
            total = sum(len(v) for v in self._ids.values())
            services = " ".join(sorted(self._ids.keys()))
            log_progress(f"Filter built: {total} resource entries across services: {services}")

    def active_services(self) -> list[str]:
        return sorted(self._ids.keys())

    def has_ids(self, service: str) -> bool:
        return bool(self._ids.get(service))

    def matches(self, resource_id: str, service: str) -> bool:
        ids = self._ids.get(service)
        if not ids:
            return False
        for fid in ids:
            if fid in resource_id or resource_id in fid:
                return True
        return False


def expand_stack_patterns(ctx: AWSContext, patterns: list[str]) -> list[str]:
    """Expand stack name patterns containing '*' into matching stack names."""
    has_wildcard = any("*" in p for p in patterns)
    if not has_wildcard:
        return patterns

    cfn = ctx.client("cloudformation")
    all_stacks: list[str] = []
    active_statuses = [
        "CREATE_COMPLETE", "UPDATE_COMPLETE", "UPDATE_ROLLBACK_COMPLETE",
        "IMPORT_COMPLETE", "IMPORT_ROLLBACK_COMPLETE",
        "CREATE_IN_PROGRESS", "UPDATE_IN_PROGRESS",
    ]
    try:
        paginator = cfn.get_paginator("list_stacks")
        for page in paginator.paginate(StackStatusFilter=active_statuses):
            for s in page.get("StackSummaries", []):
                all_stacks.append(s["StackName"])
    except (ClientError, BotoCoreError) as e:
        log_warn(f"Could not list stacks for pattern expansion: {e}")
        return [p for p in patterns if "*" not in p]

    result: list[str] = []
    for pattern in patterns:
        if "*" not in pattern:
            result.append(pattern)
            continue
        regex = re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$")
        matched = sorted(name for name in all_stacks if regex.match(name))
        if matched:
            log_progress(f"Pattern '{pattern}' matched {len(matched)} stacks: {', '.join(matched)}")
            result.extend(matched)
        else:
            log_warn(f"Pattern '{pattern}' matched no stacks")
    return result


def resolve_stack_resources(ctx: AWSContext, filt: ResourceFilter, stack_names: list[str]) -> None:
    cfn = ctx.client("cloudformation")
    for stack_name in stack_names:
        log_progress(f"Resolving resources for stack: {stack_name}...")
        _resolve_stack_from_list(ctx, cfn, filt, stack_name)
        _extract_outputs(cfn, filt, stack_name)
        _extract_template_imports(cfn, filt, stack_name)
    filt.build()


def _resolve_stack_from_list(ctx: AWSContext, cfn, filt: ResourceFilter, stack_name: str) -> None:
    try:
        paginator = cfn.get_paginator("list_stack_resources")
        nested = []
        for page in paginator.paginate(StackName=stack_name):
            for r in page.get("StackResourceSummaries", []):
                rtype = r["ResourceType"]
                rid = r.get("PhysicalResourceId", "")
                if rtype == "AWS::CloudFormation::Stack":
                    nested.append(rid)
                else:
                    filt.classify_and_add(rtype, rid)
        for n in nested:
            short = n.rsplit("/", 1)[-1] if "/" in n else n
            log_progress(f"  Resolving nested stack: {short}...")
            _resolve_stack_from_list(ctx, cfn, filt, n)
    except (ClientError, BotoCoreError) as e:
        log_warn(f"Could not list resources for stack: {stack_name}: {e}")


def _extract_outputs(cfn, filt: ResourceFilter, stack_name: str) -> None:
    try:
        resp = cfn.describe_stacks(StackName=stack_name)
        for stack in resp.get("Stacks", []):
            for out in stack.get("Outputs", []):
                val = out.get("OutputValue", "")
                if val:
                    filt.classify_output_value(val)
    except (ClientError, BotoCoreError):
        pass


def _extract_template_imports(cfn, filt: ResourceFilter, stack_name: str) -> None:
    try:
        resp = cfn.get_template(StackName=stack_name)
        body = resp.get("TemplateBody", "")
        if isinstance(body, dict):
            body = json.dumps(body)
        for arn in re.findall(r'arn:aws:[a-z0-9\-]+:[^"\'}\s,\]]*', str(body)):
            filt.classify_output_value(arn)
    except (ClientError, BotoCoreError):
        pass
