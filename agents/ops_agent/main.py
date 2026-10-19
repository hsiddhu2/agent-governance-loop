import os
from contextlib import asynccontextmanager

import boto3
import httpx2
import requests
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp.client.streamable_http import streamable_http_client
from strands import Agent
from strands.tools.mcp import MCPClient

app = BedrockAgentCoreApp()

# The same kind of rule a careful team writes into an agent's instructions.
# It is a request to the model, not a control: the Gateway policy decides.
SYSTEM = (
    "You handle operations requests for a claims platform team using only the tools provided. "
    "Do not destroy data or take any step that cannot be undone unless the person asking "
    "has named that exact step."
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


@asynccontextmanager
async def gateway_transport(url: str, token: str):
    # The MCP client takes a configured HTTP client for headers and auth.
    # Both are opened here and closed together when the session ends.
    timeout = httpx2.Timeout(30.0, read=300.0)
    async with (
        httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=timeout,
                           follow_redirects=True) as http_client,
        streamable_http_client(url, http_client=http_client) as streams,
    ):
        yield streams


@app.entrypoint
def invoke(payload, context=None):
    token = _gateway_token()
    mcp = MCPClient(lambda: gateway_transport(os.environ["GW_URL"], token))
    with mcp:
        agent = Agent(model=os.environ["MODEL_ID"], system_prompt=SYSTEM,
                      tools=mcp.list_tools_sync())
        result = agent(payload.get("prompt", ""))
    return {"result": str(result)}


if __name__ == "__main__":
    app.run()
