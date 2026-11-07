# RDS Module for Campus Medical Assistance
# Creates PostgreSQL database with Multi-AZ, encryption, and backups

# ============================================================
# RDS SUBNET GROUP
# ============================================================

resource "aws_db_subnet_group" "main" {
  name       = "${var.project_name}-${var.environment}-db-subnet-group"
  subnet_ids = var.database_subnet_ids

  tags = {
    Name        = "${var.project_name}-${var.environment}-db-subnet-group"
    Environment = var.environment
  }
}

# ============================================================
# RDS INSTANCE
# ============================================================

resource "aws_db_instance" "main" {
  identifier             = "${var.project_name}-${var.environment}"
  engine                 = "postgres"
  engine_version         = var.engine_version
  instance_class         = var.instance_class
  allocated_storage      = var.allocated_storage
  max_allocated_storage  = var.max_allocated_storage
  storage_encrypted      = true
  storage_type           = "gp3"
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = var.security_group_ids
  username               = var.username
  password               = var.password != "" ? var.password : random_password.db_password.result
  port                   = 5432
  parameter_group_name   = aws_db_parameter_group.main.name
  option_group_name      = aws_db_option_group.main.name

  # Backup configuration
  backup_retention_period = var.backup_retention_period
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:00-mon:05:00"
  copy_tags_to_snapshot   = true
  deletion_protection     = var.deletion_protection
  skip_final_snapshot     = false
  final_snapshot_identifier = "${var.project_name}-${var.environment}-final-snapshot-${formatdate("YYYYMMDDHHmmss", timestamp())}"

  # Multi-AZ
  multi_az               = var.multi_az
  publicly_accessible    = var.publicly_accessible

  # Performance insights
  performance_insights_enabled = true
  performance_insights_retention_period = 7

  # Monitoring
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.enhanced_monitoring.arn

  # Logging
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  tags = {
    Name        = "${var.project_name}-${var.environment}-db"
    Environment = var.environment
  }
}

# ============================================================
# DB PARAMETER GROUP
# ============================================================

resource "aws_db_parameter_group" "main" {
  name        = "${var.project_name}-${var.environment}-pg-params"
  family      = "postgres15"
  description = "Custom parameter group for ${var.project_name}"

  parameter {
    name  = "log_statement"
    value = "all"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }

  parameter {
    name  = "log_connections"
    value = "on"
  }

  parameter {
    name  = "log_disconnections"
    value = "on"
  }

  parameter {
    name  = "log_lock_waits"
    value = "on"
  }

  parameter {
    name  = "log_temp_files"
    value = "0"
  }

  parameter {
    name  = "log_autovacuum_min_duration"
    value = "1000"
  }

  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
  }

  parameter {
    name  = "pg_stat_statements.track"
    value = "all"
  }

  parameter {
    name  = "pg_stat_statements.max"
    value = "10000"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-pg-params"
    Environment = var.environment
  }
}

# ============================================================
# DB OPTION GROUP
# ============================================================

resource "aws_db_option_group" "main" {
  name        = "${var.project_name}-${var.environment}-pg-options"
  engine_name = "postgres"
  major_engine_version = "15"
  description = "Option group for ${var.project_name}"

  tags = {
    Name        = "${var.project_name}-${var.environment}-pg-options"
    Environment = var.environment
  }
}

# ============================================================
# RANDOM PASSWORD (fallback if not provided)
# ============================================================

resource "random_password" "db_password" {
  length  = 32
  special = false
}

# ============================================================
# IAM ROLE FOR ENHANCED MONITORING
# ============================================================

resource "aws_iam_role" "enhanced_monitoring" {
  name = "${var.project_name}-${var.environment}-rds-monitoring"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "monitoring.rds.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "enhanced_monitoring" {
  role       = aws_iam_role.enhanced_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# ============================================================
# DATABASE INITIALIZATION (optional - run migrations)
# ============================================================

# Note: Database schema initialization should be done via application startup
# or as a separate migration step. The application handles migrations via Alembic.

# ============================================================
# OUTPUTS
# ============================================================

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