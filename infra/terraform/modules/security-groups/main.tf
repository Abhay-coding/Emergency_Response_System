# Security Groups Module for Campus Medical Assistance

# ============================================================
# ALB Security Group
# ============================================================

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-${var.environment}-alb"
  description = "Security group for Application Load Balancer"
  vpc_id      = var.vpc_id

  # HTTP from allowed CIDR blocks
  dynamic "ingress" {
    for_each = var.alb_cidr_blocks
    content {
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "HTTP from ${ingress.value}"
    }
  }

  # HTTPS from allowed CIDR blocks
  dynamic "ingress" {
    for_each = var.alb_cidr_blocks
    content {
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
      description = "HTTPS from ${ingress.value}"
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-alb-sg"
    Environment = var.environment
  }
}

# ============================================================
# ECS Tasks Security Group (API and Worker)
# ============================================================

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-${var.environment}-ecs-tasks"
  description = "Security group for ECS tasks (API and Worker)"
  vpc_id      = var.vpc_id

  # Allow inbound from ALB security group on container port
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Allow traffic from ALB"
  }

  # Allow inbound from EFS security group (if needed)
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.efs.id]
    description     = "Allow NFS from EFS"
  }

  # Allow all outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-ecs-tasks-sg"
    Environment = var.environment
  }
}

# ============================================================
# RDS Security Group
# ============================================================

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-${var.environment}-rds"
  description = "Security group for RDS PostgreSQL"
  vpc_id      = var.vpc_id

  # Allow PostgreSQL from ECS tasks
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
    description     = "PostgreSQL from ECS tasks"
  }

  # Allow PostgreSQL from VPC CIDR (for bastion/debug)
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "PostgreSQL from VPC (bastion)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-rds-sg"
    Environment = var.environment
  }
}

# ============================================================
# ElastiCache Security Group
# ============================================================

resource "aws_security_group" "elasticache" {
  name        = "${var.project_name}-${var.environment}-elasticache"
  description = "Security group for ElastiCache Redis"
  vpc_id      = var.vpc_id

  # Allow Redis from ECS tasks
  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
    description     = "Redis from ECS tasks"
  }

  # Allow Redis from VPC CIDR (for bastion/debug)
  ingress {
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "Redis from VPC (bastion)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-elasticache-sg"
    Environment = var.environment
  }
}

# ============================================================
# EFS Security Group
# ============================================================

resource "aws_security_group" "efs" {
  name        = "${var.project_name}-${var.environment}-efs"
  description = "Security group for EFS"
  vpc_id      = var.vpc_id

  # Allow NFS from ECS tasks
  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
    description     = "NFS from ECS tasks"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-efs-sg"
    Environment = var.environment
  }
}

# ============================================================
# OUTPUTS
# ============================================================

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