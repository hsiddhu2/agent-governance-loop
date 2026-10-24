// The support agent may read a ticket and look up the claim it is about, through the
// minimized claim API. Nothing else: every ops tool, including the full claim file and
// the purge, falls to default deny for this agent, and the purge also to its forbid.
// Pinned to the support agent's own client and to this Gateway, so no other agent or
// client of the pool gets these tools, and the rule never applies to another
// Gateway that later shares the policy engine.
permit(
  principal == AgentCore::OAuthUser::"<client-4>",
  action in [
    AgentCore::Action::"support___get_ticket",
    AgentCore::Action::"ops___get_claim"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-hxhwh522lk"
);
