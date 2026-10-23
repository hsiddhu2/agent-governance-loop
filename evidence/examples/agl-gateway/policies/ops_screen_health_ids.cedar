suppressOutput(
  principal,
  action == AgentCore::Action::"ops___get_claim_record",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-hxhwh522lk"
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(["CA_HEALTH_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER"], [context.output.policyholder, context.output.health]).categories().contains("CA_HEALTH_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["CA_HEALTH_NUMBER", "UK_NATIONAL_HEALTH_SERVICE_NUMBER"], [context.output.policyholder, context.output.health]).categories().contains("UK_NATIONAL_HEALTH_SERVICE_NUMBER")
};
