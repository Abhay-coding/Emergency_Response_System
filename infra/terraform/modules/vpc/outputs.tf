# VPC Module Outputs

output "vpc_id" {
  value       = aws_vpc.main.id
  description = "VPC ID"
}

output "vpc_cidr" {
  value       = aws_vpc.main.cidr_block
  description = "VPC CIDR block"
}

output "public_subnet_ids" {
  value       = aws_subnet.public[*].id
  description = "Public subnet IDs"
}

output "private_subnet_ids" {
  value       = aws_subnet.private[*].id
  description = "Private subnet IDs"
}

output "database_subnet_ids" {
  value       = aws_subnet.database[*].id
  description = "Database subnet IDs"
}

output "availability_zones" {
  value       = data.aws_availability_zones.available.names
  description = "Availability zones used"
}

output "nat_gateway_ids" {
  value       = aws_nat_gateway.main[*].id
  description = "NAT Gateway IDs"
}

output "db_subnet_group_name" {
  value       = aws_db_subnet_group.main.name
  description = "Database subnet group name"
}

output "vpc_endpoint_security_group_id" {
  value       = aws_security_group.vpc_endpoints.id
  description = "VPC endpoints security group ID"
}