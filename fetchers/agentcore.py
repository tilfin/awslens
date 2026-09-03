"""Amazon Bedrock AgentCore control-plane resource fetcher."""

from datetime import datetime

from botocore.exceptions import ClientError, BotoCoreError

from core.context import AWSContext
from core.filter import ResourceFilter
from core.logging import safe_call
from core.output import Section


def fetch_agentcore(ctx: AWSContext, filt: ResourceFilter) -> list[Section]:
    """Collect the AgentCore resources used to deploy and operate agents.

    AgentCore exposes several resource families from one control-plane client.
    They are intentionally collected in a single section so ``--stack`` can
    filter every ``AWS::BedrockAgentCore::*`` resource consistently.
    """
    if filt.enabled and not filt.has_ids("agentcore"):
        return []

    client = ctx.client("bedrock-agentcore-control")
    data = {
        "runtimes": _fetch_runtimes(client, filt),
        "gateways": _fetch_gateways(client, filt),
        "memories": _fetch_memories(client, filt),
        "browsers": _fetch_browsers(client, filt),
        "browser_profiles": _fetch_browser_profiles(client, filt),
        "code_interpreters": _fetch_code_interpreters(client, filt),
        "workload_identities": _fetch_workload_identities(client, filt),
        "evaluators": _fetch_evaluators(client, filt),
        "policy_engines": _fetch_policy_engines(client, filt),
        "online_evaluation_configs": _fetch_online_evaluation_configs(client, filt),
    }
    data = {key: value for key, value in data.items() if value}
    return [Section("Bedrock AgentCore", data)] if data else []


def _list_all(client, label: str, operation: str, result_key: str, **params) -> list[dict]:
    """List every page for a simple nextToken-based AgentCore API."""
    result: list[dict] = []
    while True:
        response = safe_call(label, getattr(client, operation), **params)
        if not response:
            return result
        result.extend(response.get(result_key, []))
        token = response.get("nextToken")
        if not token:
            return result
        params["nextToken"] = token


def _get(client, label: str, operation: str, **params) -> dict | None:
    try:
        return getattr(client, operation)(**params)
    except (ClientError, BotoCoreError):
        return None


def _matches(filt: ResourceFilter, *identifiers: object) -> bool:
    if not filt.enabled:
        return True
    return any(
        identifier and filt.matches(str(identifier), "agentcore")
        for identifier in identifiers
    )


def _time(value: object) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _value(value: object) -> object:
    """Convert SDK values to YAML-safe values without exposing secret values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_value(item) for item in value]
    return value


def _fetch_runtimes(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(client, "AgentCore runtimes", "list_agent_runtimes", "agentRuntimes")
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("agentRuntimeName"), summary.get("agentRuntimeId"), summary.get("agentRuntimeArn")):
            continue
        params = {"agentRuntimeId": summary["agentRuntimeId"]}
        if summary.get("agentRuntimeVersion"):
            params["agentRuntimeVersion"] = summary["agentRuntimeVersion"]
        details = _get(client, "AgentCore runtime", "get_agent_runtime", **params) or summary
        artifact = details.get("agentRuntimeArtifact") or {}
        result.append({
            "name": details.get("agentRuntimeName"),
            "id": details.get("agentRuntimeId"),
            "arn": details.get("agentRuntimeArn"),
            "version": details.get("agentRuntimeVersion"),
            "status": details.get("status"),
            "description": details.get("description"),
            "role": details.get("roleArn"),
            "protocol": details.get("protocolConfiguration"),
            "network": _value(details.get("networkConfiguration")),
            "lifecycle": _value(details.get("lifecycleConfiguration")),
            "workload_identity": (details.get("workloadIdentityDetails") or {}).get("workloadIdentityArn"),
            "container_uri": (artifact.get("containerConfiguration") or {}).get("containerUri"),
            "code": _value(artifact.get("codeConfiguration")),
            "environment_vars": sorted((details.get("environmentVariables") or {}).keys()),
            "authorizer": _value(details.get("authorizerConfiguration")),
            "request_header_allowlist": (details.get("requestHeaderConfiguration") or {}).get("requestHeaderAllowlist", []),
            "created_at": _time(details.get("createdAt")),
            "updated_at": _time(details.get("lastUpdatedAt")),
            "failure_reason": details.get("failureReason"),
            "endpoints": _fetch_runtime_endpoints(client, details.get("agentRuntimeId"), filt),
        })
    return result


def _fetch_runtime_endpoints(client, runtime_id: str | None, filt: ResourceFilter) -> list[dict]:
    if not runtime_id:
        return []
    endpoints = _list_all(
        client, "AgentCore runtime endpoints", "list_agent_runtime_endpoints",
        "runtimeEndpoints", agentRuntimeId=runtime_id,
    )
    return [
        {
            "name": endpoint.get("name"),
            "id": endpoint.get("id"),
            "arn": endpoint.get("agentRuntimeEndpointArn"),
            "status": endpoint.get("status"),
            "live_version": endpoint.get("liveVersion"),
            "target_version": endpoint.get("targetVersion"),
            "description": endpoint.get("description"),
            "created_at": _time(endpoint.get("createdAt")),
            "updated_at": _time(endpoint.get("lastUpdatedAt")),
        }
        for endpoint in endpoints
        if _matches(filt, endpoint.get("name"), endpoint.get("id"), endpoint.get("agentRuntimeEndpointArn"))
        or _matches(filt, runtime_id)
    ]


def _fetch_gateways(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(client, "AgentCore gateways", "list_gateways", "items")
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("name"), summary.get("gatewayId")):
            continue
        details = _get(client, "AgentCore gateway", "get_gateway", gatewayIdentifier=summary["gatewayId"]) or summary
        result.append({
            "name": details.get("name"),
            "id": details.get("gatewayId"),
            "arn": details.get("gatewayArn"),
            "url": details.get("gatewayUrl"),
            "status": details.get("status"),
            "status_reasons": details.get("statusReasons", []),
            "description": details.get("description"),
            "role": details.get("roleArn"),
            "protocol_type": details.get("protocolType"),
            "protocol": _value(details.get("protocolConfiguration")),
            "authorizer_type": details.get("authorizerType"),
            "authorizer": _value(details.get("authorizerConfiguration")),
            "kms_key_arn": details.get("kmsKeyArn"),
            "policy_engine": _value(details.get("policyEngineConfiguration")),
            "workload_identity": (details.get("workloadIdentityDetails") or {}).get("workloadIdentityArn"),
            "exception_level": details.get("exceptionLevel"),
            "created_at": _time(details.get("createdAt")),
            "updated_at": _time(details.get("updatedAt")),
            "targets": _fetch_gateway_targets(client, details.get("gatewayId"), filt),
        })
    return result


def _fetch_gateway_targets(client, gateway_id: str | None, filt: ResourceFilter) -> list[dict]:
    if not gateway_id:
        return []
    summaries = _list_all(
        client, "AgentCore gateway targets", "list_gateway_targets", "items",
        gatewayIdentifier=gateway_id,
    )
    result = []
    for summary in summaries:
        details = _get(
            client, "AgentCore gateway target", "get_gateway_target",
            gatewayIdentifier=gateway_id, targetId=summary["targetId"],
        ) or summary
        config = details.get("targetConfiguration") or {}
        result.append({
            "name": details.get("name"),
            "id": details.get("targetId"),
            "status": details.get("status"),
            "status_reasons": details.get("statusReasons", []),
            "description": details.get("description"),
            "configuration": _target_configuration(config),
            "credential_provider_types": [
                item.get("credentialProviderType")
                for item in details.get("credentialProviderConfigurations", [])
            ],
            "last_synchronized_at": _time(details.get("lastSynchronizedAt")),
            "created_at": _time(details.get("createdAt")),
            "updated_at": _time(details.get("updatedAt")),
        })
    return result


def _target_configuration(config: dict) -> dict | None:
    if not config:
        return None
    target_type = next((key for key, value in config.items() if value), "unknown")
    result = {"type": target_type}
    mcp = config.get("mcp") or {}
    if mcp:
        lambda_config = mcp.get("lambda") or {}
        server_config = mcp.get("mcpServer") or {}
        api_gateway = mcp.get("apiGateway") or {}
        result.update({
            "lambda_arn": lambda_config.get("lambdaArn"),
            "mcp_server_endpoint": server_config.get("endpoint"),
            "api_gateway": _value(api_gateway) if api_gateway else None,
            "has_openapi_schema": bool(mcp.get("openApiSchema")),
            "has_smithy_model": bool(mcp.get("smithyModel")),
        })
    return result


def _fetch_memories(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(client, "AgentCore memories", "list_memories", "memories")
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("id"), summary.get("arn")):
            continue
        response = _get(client, "AgentCore memory", "get_memory", memoryId=summary["id"])
        memory = (response or {}).get("memory", summary)
        result.append({
            "name": memory.get("name"),
            "id": memory.get("id"),
            "arn": memory.get("arn"),
            "status": memory.get("status"),
            "description": memory.get("description"),
            "encryption_key_arn": memory.get("encryptionKeyArn"),
            "execution_role": memory.get("memoryExecutionRoleArn"),
            "event_expiry_duration": memory.get("eventExpiryDuration"),
            "strategies": _value(memory.get("strategies", [])),
            "created_at": _time(memory.get("createdAt")),
            "updated_at": _time(memory.get("updatedAt")),
            "failure_reason": memory.get("failureReason"),
        })
    return result


def _fetch_browsers(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(client, "AgentCore browsers", "list_browsers", "browserSummaries")
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("name"), summary.get("browserId"), summary.get("browserArn")):
            continue
        details = _get(client, "AgentCore browser", "get_browser", browserId=summary["browserId"]) or summary
        result.append(_service_tool_info(details, "browser"))
    return result


def _fetch_browser_profiles(client, filt: ResourceFilter) -> list[dict]:
    profiles = _list_all(client, "AgentCore browser profiles", "list_browser_profiles", "profileSummaries")
    return [
        {
            "name": profile.get("name"), "id": profile.get("profileId"), "arn": profile.get("profileArn"),
            "status": profile.get("status"), "description": profile.get("description"),
            "last_saved_at": _time(profile.get("lastSavedAt")),
            "browser_id": profile.get("lastSavedBrowserId"),
            "created_at": _time(profile.get("createdAt")), "updated_at": _time(profile.get("lastUpdatedAt")),
        }
        for profile in profiles
        if _matches(filt, profile.get("name"), profile.get("profileId"), profile.get("profileArn"))
    ]


def _fetch_code_interpreters(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(client, "AgentCore code interpreters", "list_code_interpreters", "codeInterpreterSummaries")
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("name"), summary.get("codeInterpreterId"), summary.get("codeInterpreterArn")):
            continue
        details = _get(client, "AgentCore code interpreter", "get_code_interpreter", codeInterpreterId=summary["codeInterpreterId"]) or summary
        result.append(_service_tool_info(details, "codeInterpreter"))
    return result


def _service_tool_info(details: dict, id_key: str) -> dict:
    prefix = "browser" if id_key == "browser" else "codeInterpreter"
    return {
        "name": details.get("name"), "id": details.get(f"{prefix}Id"), "arn": details.get(f"{prefix}Arn"),
        "status": details.get("status"), "description": details.get("description"),
        "execution_role": details.get("executionRoleArn"), "network": _value(details.get("networkConfiguration")),
        "recording": _value(details.get("recording")) if prefix == "browser" else None,
        "browser_signing": _value(details.get("browserSigning")) if prefix == "browser" else None,
        "created_at": _time(details.get("createdAt")), "updated_at": _time(details.get("lastUpdatedAt")),
        "failure_reason": details.get("failureReason"),
    }


def _fetch_workload_identities(client, filt: ResourceFilter) -> list[dict]:
    identities = _list_all(client, "AgentCore workload identities", "list_workload_identities", "workloadIdentities")
    result = []
    for identity in identities:
        if not _matches(filt, identity.get("name"), identity.get("workloadIdentityArn")):
            continue
        details = _get(client, "AgentCore workload identity", "get_workload_identity", name=identity["name"]) or identity
        result.append({
            "name": details.get("name"), "arn": details.get("workloadIdentityArn"),
            "allowed_oauth2_return_urls": details.get("allowedResourceOauth2ReturnUrls", []),
            "created_at": _time(details.get("createdTime")), "updated_at": _time(details.get("lastUpdatedTime")),
        })
    return result


def _fetch_evaluators(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(client, "AgentCore evaluators", "list_evaluators", "evaluators")
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("evaluatorName"), summary.get("evaluatorId"), summary.get("evaluatorArn")):
            continue
        details = _get(client, "AgentCore evaluator", "get_evaluator", evaluatorId=summary["evaluatorId"]) or summary
        result.append({
            "name": details.get("evaluatorName"), "id": details.get("evaluatorId"), "arn": details.get("evaluatorArn"),
            "level": details.get("level"), "status": details.get("status"), "description": details.get("description"),
            "config": _value(details.get("evaluatorConfig")), "locked": details.get("lockedForModification"),
            "created_at": _time(details.get("createdAt")), "updated_at": _time(details.get("updatedAt")),
        })
    return result


def _fetch_policy_engines(client, filt: ResourceFilter) -> list[dict]:
    engines = _list_all(client, "AgentCore policy engines", "list_policy_engines", "policyEngines")
    result = []
    for engine in engines:
        if not _matches(filt, engine.get("name"), engine.get("policyEngineId"), engine.get("policyEngineArn")):
            continue
        engine_id = engine["policyEngineId"]
        policies = _list_all(client, "AgentCore policies", "list_policies", "policies", policyEngineId=engine_id)
        result.append({
            "name": engine.get("name"), "id": engine_id, "arn": engine.get("policyEngineArn"),
            "status": engine.get("status"), "status_reasons": engine.get("statusReasons", []),
            "description": engine.get("description"),
            "created_at": _time(engine.get("createdAt")), "updated_at": _time(engine.get("updatedAt")),
            "policies": [
                {
                    "name": policy.get("name"), "id": policy.get("policyId"), "arn": policy.get("policyArn"),
                    "status": policy.get("status"), "description": policy.get("description"),
                    "definition": _value(policy.get("definition")),
                }
                for policy in policies
            ],
        })
    return result


def _fetch_online_evaluation_configs(client, filt: ResourceFilter) -> list[dict]:
    summaries = _list_all(
        client, "AgentCore online evaluation configurations",
        "list_online_evaluation_configs", "onlineEvaluationConfigs",
    )
    result = []
    for summary in summaries:
        if not _matches(filt, summary.get("onlineEvaluationConfigName"), summary.get("onlineEvaluationConfigId"), summary.get("onlineEvaluationConfigArn")):
            continue
        details = _get(
            client, "AgentCore online evaluation configuration", "get_online_evaluation_config",
            onlineEvaluationConfigId=summary["onlineEvaluationConfigId"],
        ) or summary
        result.append({
            "name": details.get("onlineEvaluationConfigName"), "id": details.get("onlineEvaluationConfigId"),
            "arn": details.get("onlineEvaluationConfigArn"), "status": details.get("status"),
            "execution_status": details.get("executionStatus"), "description": details.get("description"),
            "rule": _value(details.get("rule")), "data_source": _value(details.get("dataSourceConfig")),
            "evaluators": _value(details.get("evaluators", [])), "output": _value(details.get("outputConfig")),
            "execution_role": details.get("evaluationExecutionRoleArn"),
            "created_at": _time(details.get("createdAt")), "updated_at": _time(details.get("updatedAt")),
            "failure_reason": details.get("failureReason"),
        })
    return result
