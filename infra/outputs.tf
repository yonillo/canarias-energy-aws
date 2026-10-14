output "s3_datalake_bucket_name" {
  description = "Nombre del bucket S3 configurado como Data Lake"
  value       = aws_s3_bucket.energy_datalake.bucket
}

output "dynamodb_table_name" {
  description = "Nombre de la tabla DynamoDB para acceso de baja latencia (Hot Path)"
  value       = aws_dynamodb_table.islands_realtime.name
}

output "lambda_function_arn" {
  description = "ARN de la función AWS Lambda de ingesta"
  value       = aws_lambda_function.ingestor_lambda.arn
}

output "eventbridge_schedule" {
  description = "Expresión de programación del EventBridge Scheduler"
  value       = aws_cloudwatch_event_rule.every_15_mins.schedule_expression
}
