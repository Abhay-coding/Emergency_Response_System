# IAM Module Outputs

output "ecs_execution_role_arn" {
  value       = aws_iam_role.ecs_execution.arn
  description = "ECS Execution Role ARN"
}

output "ecs_task_role_arn" {
  value       = aws_iam_role.ecs_task.arn
  description = "ECS Task Role ARN"
}

output "ecs_service_role_arn" {
  value       = aws_iam_role.ecs_service.arn
  description = "ECS Service Role ARN"
}

output "autoscaling_role_arn" {
  value       = aws_iam_role.autoscaling.arn
  description = "Autoscaling Role ARN"
}