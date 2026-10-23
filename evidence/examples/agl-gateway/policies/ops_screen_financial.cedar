suppressOutput(
  principal,
  action == AgentCore::Action::"ops___get_claim_record",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<account-1>:gateway/agl-gateway-hxhwh522lk"
)
when guardrails {
  BedrockGuardrails::SensitiveInformation(["US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"], [context.output.policyholder, context.output.health]).categories().contains("US_BANK_ACCOUNT_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"], [context.output.policyholder, context.output.health]).categories().contains("US_BANK_ROUTING_NUMBER") ||
  BedrockGuardrails::SensitiveInformation(["US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER", "CREDIT_DEBIT_CARD_NUMBER"], [context.output.policyholder, context.output.health]).categories().contains("CREDIT_DEBIT_CARD_NUMBER")
};
