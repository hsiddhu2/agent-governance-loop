suppressOutput(
  principal,
  action == AgentCore::Action::"ops___get_claim_record",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-hxhwh522lk"
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(["NAME", "ADDRESS", "PHONE", "EMAIL", "AGE"], [context.output.policyholder, context.output.health]).categories().contains("NAME") ||
  BedrockGuardrails::SensitiveInformation(["NAME", "ADDRESS", "PHONE", "EMAIL", "AGE"], [context.output.policyholder, context.output.health]).categories().contains("ADDRESS") ||
  BedrockGuardrails::SensitiveInformation(["NAME", "ADDRESS", "PHONE", "EMAIL", "AGE"], [context.output.policyholder, context.output.health]).categories().contains("PHONE") ||
  BedrockGuardrails::SensitiveInformation(["NAME", "ADDRESS", "PHONE", "EMAIL", "AGE"], [context.output.policyholder, context.output.health]).categories().contains("EMAIL") ||
  BedrockGuardrails::SensitiveInformation(["NAME", "ADDRESS", "PHONE", "EMAIL", "AGE"], [context.output.policyholder, context.output.health]).categories().contains("AGE")
};
