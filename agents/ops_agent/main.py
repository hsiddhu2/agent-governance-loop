import os

import boto3
import requests
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamablehttp_client
from strands import Agent
from strands.tools.mcp import MCPClient

app = BedrockAgentCoreApp()

# A prompt-level instruction. Kept here to show that it is not a control:
# the Gateway policy is what decides whether a destructive call runs.
SYSTEM = (
    "You are an operations agent. You manage data stores through the tools you are given. "
    "NEVER run destructive or irreversible operations unless the user explicitly requests them."
)


def _gateway_token() -> str:
    client_id = os.environ["GW_CLIENT_ID"]
    secret = boto3.client("cognito-idp").describe_user_pool_client(
        UserPoolId=os.environ["GW_USER_POOL_ID"], ClientId=client_id,
    )["UserPoolClient"]["ClientSecret"]
    resp = requests.post(os.environ["GW_TOKEN_URL"], timeout=10, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": secret,
        "scope": os.environ["GW_SCOPES"],
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


@app.entrypoint
def invoke(payload, context=None):
    token = _gateway_token()
    mcp = MCPClient(lambda: streamablehttp_client(
        os.environ["GW_URL"], headers={"Authorization": f"Bearer {token}"}))
    with mcp:
        agent = Agent(system_prompt=SYSTEM, tools=mcp.list_tools_sync())
        result = agent(payload.get("prompt", ""))
    return {"result": str(result)}


if __name__ == "__main__":
    app.run()
