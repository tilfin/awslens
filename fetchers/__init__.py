"""Service fetcher registry."""

from .cdn import fetch_cloudfront
from .storage import fetch_s3
from .compute import fetch_lambda_svc, fetch_ecs, fetch_ecr
from .networking import fetch_vpc, fetch_securitygroup, fetch_alb
from .database import fetch_rds, fetch_dynamodb
from .messaging import fetch_sns, fetch_sqs, fetch_eventbridge
from .api import fetch_apigateway
from .dns_and_certs import fetch_route53, fetch_acm
from .monitoring import fetch_cloudwatch, fetch_stepfunctions, fetch_secrets
from .iam import fetch_iam_dependencies
from .apprunner import fetch_apprunner
from .cfn import fetch_cfn_stacks

ALL_SERVICES = [
    "cloudfront", "s3", "alb", "lambda", "sns", "sqs", "apigateway",
    "route53", "acm", "rds", "dynamodb", "secrets", "vpc",
    "securitygroup", "ecs", "ecr", "cloudwatch", "eventbridge",
    "apprunner", "stepfunctions", "iam_dependencies", "cfn_stacks",
]

SERVICE_FETCHERS = {
    "cloudfront": fetch_cloudfront,
    "s3": fetch_s3,
    "alb": fetch_alb,
    "lambda": fetch_lambda_svc,
    "sns": fetch_sns,
    "sqs": fetch_sqs,
    "apigateway": fetch_apigateway,
    "route53": fetch_route53,
    "acm": fetch_acm,
    "rds": fetch_rds,
    "dynamodb": fetch_dynamodb,
    "secrets": fetch_secrets,
    "vpc": fetch_vpc,
    "securitygroup": fetch_securitygroup,
    "ecs": fetch_ecs,
    "ecr": fetch_ecr,
    "cloudwatch": fetch_cloudwatch,
    "eventbridge": fetch_eventbridge,
    "apprunner": fetch_apprunner,
    "stepfunctions": fetch_stepfunctions,
    "iam_dependencies": fetch_iam_dependencies,
    "cfn_stacks": fetch_cfn_stacks,
}
