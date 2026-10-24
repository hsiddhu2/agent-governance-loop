suppressOutput(
  principal,
  action == AgentCore::Action::"support___get_ticket",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-gxl9ipizia"
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(["US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"], [context.output.subject, context.output.body]).categories().contains("US_BANK_ACCOUNT_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"], [context.output.subject, context.output.body]).categories().contains("US_BANK_ROUTING_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"], [context.output.subject, context.output.body]).categories().contains("CREDIT_DEBIT_CARD_NUMBER")
};
