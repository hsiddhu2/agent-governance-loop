"""What exists, who each caller is, what policy allows, and whether policy is enforced.

Everything here comes from the AgentCore control plane at the time of the run.
Runtime environment variables are never written: they can hold configuration a
team did not mean to hand an auditor.
"""
import json
import re

from botocore.exceptions import ClientError

# Statements a policy engine holds. Comments are kept, since they state intent.
# suppressOutput is the effect of a guardrail screen, which withholds a tool's result.
EFFECT = re.compile(r"^\s*(permit|forbid|suppressOutput)\s*\(", re.MULTILINE)


def gateway(control, gateway_id: str) -> dict:
    gw = control.get_gateway(gatewayIdentifier=gateway_id)
    gw.pop("ResponseMetadata", None)
    return gw


def targets(control, gateway_id: str) -> list[dict]:
    found = []
    for page in control.get_paginator("list_gateway_targets").paginate(gatewayIdentifier=gateway_id):
        for t in page["items"]:
            detail = control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=t["targetId"])
            found.append({
                "targetId": t["targetId"],
                "name": t["name"],
                "status": t["status"],
                "type": t.get("targetType"),
                "configuration": detail.get("targetConfiguration"),
                "credentialProviders": detail.get("credentialProviderConfigurations"),
                "updatedAt": str(t.get("updatedAt")),
            })
    return found


def runtimes(control) -> list[dict]:
    found = []
    for page in control.get_paginator("list_agent_runtimes").paginate():
        for r in page["agentRuntimes"]:
            d = control.get_agent_runtime(agentRuntimeId=r["agentRuntimeId"])
            found.append({
                "agentRuntimeId": d["agentRuntimeId"],
                "name": d["agentRuntimeName"],
                "arn": d["agentRuntimeArn"],
                "version": d.get("agentRuntimeVersion"),
                "status": d.get("status"),
                "roleArn": d.get("roleArn"),
                "network": d.get("networkConfiguration", {}).get("networkMode"),
                "authorizer": d.get("authorizerConfiguration"),
                "workloadIdentity": d.get("workloadIdentityDetails", {}).get("workloadIdentityArn"),
                "updatedAt": str(d.get("lastUpdatedAt")),
            })
    return found


def inventory(gw: dict, gw_targets: list[dict], agent_runtimes: list[dict], cat: dict | None = None) -> dict:
    return {
        "catalog": cat or {"status": "GAP", "reason": "the Agent Registry was not read",
                           "registries": [], "records": []},
        "gateway": {
            "gatewayId": gw["gatewayId"],
            "name": gw["name"],
            "arn": gw["gatewayArn"],
            "status": gw["status"],
            "protocol": gw.get("protocolType"),
            "roleArn": gw.get("roleArn"),
            "updatedAt": str(gw.get("updatedAt")),
        },
        "targets": gw_targets,
        "runtimes": agent_runtimes,
    }


def cataloged(gw: dict, agent_runtimes: list[dict]) -> dict[str, list[str]]:
    """What the catalog should name: the Gateway by ARN or URL, each runtime by ARN."""
    found = {f"gateway {gw['name']}": [gw["gatewayArn"], gw.get("gatewayUrl")]}
    found.update({f"runtime {r['name']}": [r["arn"]] for r in agent_runtimes})
    return {label: [i for i in ids if i] for label, ids in found.items()}


def catalog(registry, wanted: dict[str, list[str]]) -> dict:
    """Which Agent Registry records in this Region name each resource, and their status.

    A record names a resource when its descriptor carries the resource's identifier or
    its provenance points at it. Only the matching labels are kept, not the descriptors,
    which can hold detail a team did not mean to hand an auditor.
    """
    try:
        registries, records = [], []
        for page in registry.get_paginator("list_registries").paginate():
            for reg in page["registries"]:
                registries.append({"name": reg["name"], "arn": reg["registryArn"],
                                   "status": reg.get("status")})
                reg_id = reg["registryArn"].rsplit("/", 1)[-1]
                for rpage in registry.get_paginator("list_registry_records").paginate(registryId=reg_id):
                    for summary in rpage["registryRecords"]:
                        detail = registry.get_registry_record(registryId=reg_id, recordId=summary["recordId"])
                        text = json.dumps([detail.get("descriptors"), detail.get("provenance")], default=str)
                        records.append({
                            "registry": reg["name"],
                            "name": summary["name"],
                            "recordType": summary["recordType"],
                            "status": summary["status"],
                            "names": sorted(label for label, ids in wanted.items()
                                            if any(i in text for i in ids)),
                        })
        return {"status": "OK", "registries": registries, "records": records}
    except ClientError as e:
        code = e.response["Error"]["Code"]
        return {"status": "GAP", "reason": f"could not read the Agent Registry: {code}",
                "registries": [], "records": []}


def jwt_authorizer(config: dict | None) -> dict | None:
    jwt = (config or {}).get("customJWTAuthorizer")
    if not jwt:
        return None
    return {
        "discoveryUrl": jwt.get("discoveryUrl"),
        "allowedClients": jwt.get("allowedClients", []),
        "allowedAudience": jwt.get("allowedAudience", []),
        "allowedScopes": jwt.get("allowedScopes", []),
    }


def identity(gw: dict, agent_runtimes: list[dict]) -> dict:
    """Who may call the Gateway, and who may call each runtime, from authorizer configuration.

    Read from the resources themselves, never from the identity provider: a client
    description from the provider can carry the client secret.
    """
    return {
        "gateway": {
            "authorizerType": gw.get("authorizerType"),
            "jwt": jwt_authorizer(gw.get("authorizerConfiguration")),
            "workloadIdentity": gw.get("workloadIdentityDetails", {}).get("workloadIdentityArn"),
        },
        "runtimes": [{
            "name": r["name"],
            "inbound": "CUSTOM_JWT" if jwt_authorizer(r["authorizer"]) else "AWS_IAM",
            "jwt": jwt_authorizer(r["authorizer"]),
            "workloadIdentity": r["workloadIdentity"],
            "roleArn": r["roleArn"],
        } for r in agent_runtimes],
    }


def engine_id(gw: dict) -> str | None:
    config = gw.get("policyEngineConfiguration")
    return config["arn"].rsplit("/", 1)[-1] if config else None


def policies(control, engine: str) -> list[dict]:
    found = []
    for page in control.get_paginator("list_policies").paginate(policyEngineId=engine):
        for p in page["policies"]:
            detail = control.get_policy(policyEngineId=engine, policyId=p["policyId"])
            # Cedar policies come back as `cedar`, guardrail screens as `policy`. A policy made
            # from a policy generation comes back as `policyGeneration`, with no statement.
            definition = detail.get("definition", {})
            source = next((k for k in ("cedar", "policy", "policyGeneration") if k in definition), None)
            statement = (definition.get("cedar") or definition.get("policy") or {}).get("statement")
            found.append({
                "policyId": detail["policyId"],
                "name": detail["name"],
                "status": detail.get("status"),
                "enforcementMode": detail.get("enforcementMode"),
                "definedAs": source,
                **({"generatedFrom": definition["policyGeneration"]} if source == "policyGeneration" else {}),
                "effects": EFFECT.findall(statement or ""),
                "updatedAt": str(detail.get("updatedAt")),
                "statement": statement,
            })
    return found


def is_screen(policy: dict) -> bool:
    return bool(policy["effects"]) and set(policy["effects"]) == {"suppressOutput"}


def enforcement(gw: dict, engine_policies: list[dict]) -> dict:
    """Whether decisions are applied. Either level can be set to record without applying.

    Enforcement is judged on the permit and forbid policies. A policy in LOG_ONLY cannot
    change a decision, so a screen left in LOG_ONLY does not weaken them. Screens are
    reported on their own. A policy whose effect cannot be read is judged with the rest.
    """
    config = gw.get("policyEngineConfiguration") or {}
    access = [p for p in engine_policies if not is_screen(p)]
    log_only = [p["name"] for p in access if p["enforcementMode"] != "ACTIVE"]
    return {
        "engineAttached": bool(config),
        "engineArn": config.get("arn"),
        "gatewayMode": config.get("mode"),
        "policies": {p["name"]: p["enforcementMode"] for p in access},
        "policiesNotEnforced": log_only,
        "screens": {p["name"]: p["enforcementMode"] for p in engine_policies if is_screen(p)},
        "enforced": config.get("mode") == "ENFORCE" and not log_only,
    }
