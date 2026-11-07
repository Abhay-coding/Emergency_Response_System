# ECS Worker Module Outputs

output "service_name" {
  value       = aws_ecs_service.worker.name
  description = "ECS Worker Service Name"
}

output "service_arn" {
  value       = aws_ecs_service.worker.arn
  description = "ECS Worker Service ARN"
}

output "task_definition_arn" {
  value       = aws_ecs_task_definition.worker.arn
  description = "Worker Task Definition ARN"
}