# Security Groups Module Outputs

output "alb_sg_id" {
  value       = aws_security_group.alb.id
  description = "ALB Security Group ID"
}

output "ecs_tasks_sg_id" {
  value       = aws_security_group.ecs_tasks.id
  description = "ECS Tasks Security Group ID"
}

output "rds_sg_id" {
  value       = aws_security_group.rds.id
  description = "RDS Security Group ID"
}

output "elasticache_sg_id" {
  value       = aws_security_group.elasticache.id
  description = "ElastiCache Security Group ID"
}

output "efs_sg_id" {
  value       = aws_security_group.efs.id
  description = "EFS Security Group ID"
}