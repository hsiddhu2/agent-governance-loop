suppressOutput(
  principal,
  action == AgentCore::Action::"support___get_ticket",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-hxhwh522lk"
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(["US_SOCIAL_SECURITY_NUMBER", "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID"], [context.output.subject, context.output.body]).categories().contains("US_SOCIAL_SECURITY_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_SOCIAL_SECURITY_NUMBER", "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID"], [context.output.subject, context.output.body]).categories().contains("US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_SOCIAL_SECURITY_NUMBER", "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID"], [context.output.subject, context.output.body]).categories().contains("US_PASSPORT_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_SOCIAL_SECURITY_NUMBER", "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER", "DRIVER_ID"], [context.output.subject, context.output.body]).categories().contains("DRIVER_ID")
};
