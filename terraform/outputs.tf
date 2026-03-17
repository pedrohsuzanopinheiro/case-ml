output "api_url" {
  description = "Base URL of the deployed API"
  value       = "https://${aws_api_gateway_rest_api.main.id}.execute-api.${var.region}.amazonaws.com/${aws_api_gateway_stage.v1.stage_name}"
}

output "table_name" {
  description = "DynamoDB table name"
  value       = aws_dynamodb_table.sobreviventes.name
}

output "lambda_function_name" {
  description = "Lambda function name"
  value       = aws_lambda_function.predictor.function_name
}
