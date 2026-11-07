# RDS Module Outputs

output "db_instance_id" {
  value       = aws_db_instance.main.id
  description = "RDS Instance ID"
}

output "db_instance_arn" {
  value       = aws_db_instance.main.arn
  description = "RDS Instance ARN"
}

output "db_endpoint" {
  value       = aws_db_instance.main.endpoint
  description = "RDS Endpoint"
}

output "db_port" {
  value       = aws_db_instance.main.port
  description = "RDS Port"
}

output "db_name" {
  value       = aws_db_instance.main.db_name
  description = "Database Name"
}

output "db_username" {
  value       = aws_db_instance.main.username
  description = "Database Username"
}

output "db_password" {
  value       = var.password != "" ? var.password : random_password.db_password.result
  description = "Database Password"
  sensitive   = true
}

output "database_url" {
  value       = "postgresql+psycopg://${aws_db_instance.main.username}:${var.password != "" ? var.password : random_password.db_password.result}@${aws_db_instance.main.endpoint}/postgres"
  description = "Database Connection URL for application"
  sensitive   = true
}

output "db_subnet_group_name" {
  value       = aws_db_subnet_group.main.name
  description = "DB Subnet Group Name"
}

output "db_parameter_group_name" {
  value       = aws_db_parameter_group.main.name
  description = "DB Parameter Group Name"
}