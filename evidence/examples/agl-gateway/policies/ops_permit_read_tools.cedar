// Read-only ops tools are allowed. Everything not permitted is denied by default.
// That includes the Gateway's built-in search tool: with five tools the agent
// has nothing to search for. A large catalog would permit it on purpose.
// get_claim_record returns the whole claim file on purpose. The ops_screen_* policies
// screen what it returns. get_claim is the minimized API a production agent gets.
// Pinned to the ops agent's own client and to this Gateway, so no other agent or
// client of the pool gets these tools, and the rule never applies to another
// Gateway that later shares the policy engine.
permit(
  principal == AgentCore::OAuthUser::"<client-2>",
  action in [
    AgentCore::Action::"ops___list_env",
    AgentCore::Action::"ops___get_claims_store",
    AgentCore::Action::"ops___get_claim",
    AgentCore::Action::"ops___get_claim_record"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-hxhwh522lk"
);
