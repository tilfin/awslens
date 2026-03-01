"""API Gateway (REST + HTTP) fetchers."""

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_apigateway(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    if filt.enabled and not filt.has_ids("apigateway"):
        return []
    sections = []
    sections.extend(_fetch_rest_apis(ctx, filt))
    sections.extend(_fetch_http_apis(ctx, filt))
    return sections


def _fetch_rest_apis(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    apigw = ctx.client("apigateway")
    resp = safe_call("REST APIs", apigw.get_rest_apis)
    if not resp:
        return []
    apis = resp.get("items", [])
    if not apis:
        return []
    result = []
    for api in apis:
        api_id = api["id"]
        base = {
            "id": api_id,
            "name": api.get("name"),
            "endpoint_type": (api.get("endpointConfiguration") or {}).get("types", [None])[0],
        }
        resources = []
        try:
            rr = apigw.get_resources(restApiId=api_id)
            for r in rr.get("items", []):
                methods = r.get("resourceMethods")
                if methods:
                    resources.append({"path": r["path"], "methods": list(methods.keys())})
        except (ClientError, BotoCoreError):
            pass
        base["resources"] = resources
        result.append(base)
    if not result:
        return []
    return [Section("API Gateway (REST)", {"rest_apis": result})]


def _fetch_http_apis(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    apigw2 = ctx.client("apigatewayv2")
    resp = safe_call("HTTP APIs", apigw2.get_apis)
    if not resp:
        return []
    apis = resp.get("Items", [])
    if not apis:
        return []
    result = [
        {"id": a["ApiId"], "name": a.get("Name"), "protocol": a.get("ProtocolType"), "endpoint": a.get("ApiEndpoint")}
        for a in apis
    ]
    return [Section("API Gateway (HTTP)", {"http_apis": result})]
