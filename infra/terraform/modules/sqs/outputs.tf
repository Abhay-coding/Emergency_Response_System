# SQS Module Outputs

output "queue_url" {
  value       = aws_sqs_queue.main.url
  description = "SQS Queue URL"
}

output "queue_arn" {
  value       = aws_sqs_queue.main.arn
  description = "SQS Queue ARN"
}

output "dead_letter_queue_url" {
  value       = aws_sqs_queue.dead_letter.url
  description = "Dead Letter Queue URL"
}

output "dead_letter_queue_arn" {
  value       = aws_sqs_queue.dead_letter.arn
  description = "Dead Letter Queue ARN"
}