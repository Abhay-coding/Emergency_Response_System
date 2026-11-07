# ElastiCache Module for Campus Medical Assistance
# Creates Redis cluster with encryption and authentication

# ============================================================
# ELASTICACHE SUBNET GROUP
# ============================================================

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project_name}-${var.environment}-cache-subnet"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name        = "${var.project_name}-${var.environment}-cache-subnet"
    Environment = var.environment
  }
}

# ============================================================
# ELASTICACHE PARAMETER GROUP
# ============================================================

resource "aws_elasticache_parameter_group" "main" {
  name        = "${var.project_name}-${var.environment}-redis-params"
  family      = var.parameter_group_family
  description = "Custom parameter group for ${var.project_name}"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }

  parameter {
    name  = "timeout"
    value = "300"
  }

  parameter {
    name  = "tcp-keepalive"
    value = "60"
  }
}

# ============================================================
# ELASTICACHE REPLICATION GROUP
# ============================================================

resource "aws_elasticache_replication_group" "main" {
  replication_group_id          = "${var.project_name}-${var.environment}-redis"
  description                   = "Redis cluster for ${var.project_name}"
  engine                        = "redis"
  engine_version                = var.engine_version
  node_type                     = var.node_type
  number_cache_clusters         = var.num_cache_nodes
  parameter_group_name          = aws_elasticache_parameter_group.main.name
  subnet_group_name             = aws_elasticache_subnet_group.main.name
  security_group_ids            = var.security_group_ids
  port                          = 6379
  automatic_failover_enabled    = var.num_cache_nodes > 1
  multi_az_enabled              = var.num_cache_nodes > 1
  at_rest_encryption_enabled    = var.at_rest_encryption
  transit_encryption_enabled    = var.transit_encryption
  auth_token                    = var.auth_token != "" ? var.auth_token : random_password.auth_token.result
  snapshot_retention_limit      = 7
  snapshot_window               = "03:00-04:00"
  maintenance_window            = "mon:04:00-mon:05:00"
  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis.arn
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }
  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis.arn
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "engine-log"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-redis"
    Environment = var.environment
  }
}

# ============================================================
# RANDOM PASSWORD FOR AUTH TOKEN
# ============================================================

resource "random_password" "auth_token" {
  length  = 32
  special = false
}

# ============================================================
# CLOUDWATCH LOG GROUP
# ============================================================

resource "aws_cloudwatch_log_group" "redis" {
  name              = "/aws/elasticache/${var.project_name}-${var.environment}-redis"
  retention_in_days = 30
}

# ============================================================
# OUTPUTS
# ============================================================

output "replication_group_id" {
  value       = aws_elasticache_replication_group.main.replication_group_id
  description = "ElastiCache Replication Group ID"
}

output "primary_endpoint" {
  value       = aws_elasticache_replication_group.main.primary_endpoint_address
  description = "Primary endpoint address"
}

output "reader_endpoint" {
  value       = aws_elasticache_replication_group.main.reader_endpoint_address
  description = "Reader endpoint address"
}

output "port" {
  value       = aws_elasticache_replication_group.main.port
  description = "Redis port"
}

output "auth_token" {
  value       = var.auth_token != "" ? var.auth_token : random_password.auth_token.result
  description = "Redis auth token"
  sensitive   = true
}