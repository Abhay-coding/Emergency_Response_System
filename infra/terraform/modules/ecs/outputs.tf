# ECS Module Outputs

output "cluster_name" {
  value       = aws_ecs_cluster.main.name
  description = "ECS Cluster Name"
}

output "cluster_arn" {
  value       = aws_ecs_cluster.main.arn
  description = "ECS Cluster ARN"
}

output "service_name" {
  value       = aws_ecs_service.main.name
  description = "ECS Service Name"
}

output "service_arn" {
  value       = aws_ecs_service.main.arn
  description = "ECS Service ARN"
}

output "task_definition_arn" {
  value       = aws_ecs_task_definition.main.arn
  description = "Task Definition ARN"
}