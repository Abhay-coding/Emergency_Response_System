# ECS Worker Module for Campus Medical Assistance
# Creates ECS service for the notification worker

# ============================================================
# TASK DEFINITION
# ============================================================

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-${var.environment}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn
  runtime_platform {
    cpu_architecture       = "X86_64"
    operating_system_family = "LINUX"
  }

  container_definitions = jsonencode([
    {
      name      = "${var.project_name}-worker"
      image     = var.container_image
      essential = true
      command   = ["python", "-m", "app.worker"]
      environment = [
        for key, value in var.environment_variables :
        { name = key, value = value }
      ]
      secrets = [
        for secret in var.secrets :
        { name = secret.name, valueFrom = secret.valueFrom }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }
      healthCheck = {
        command  = ["CMD-SHELL", "python -c \"import os; os.kill(1, 0)\""]
        interval = 30
        timeout  = 5
        retries  = 3
      }
      user = "appuser"
    }
  ])

  tags = {
    Name        = "${var.project_name}-${var.environment}-worker-task"
    Environment = var.environment
  }
}

# ============================================================
# SERVICE
# ============================================================

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.environment}-worker"
  cluster         = var.cluster_name
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_configuration {
    maximum_percent         = 200
    minimum_healthy_percent = 50
  }

  enable_ecs_managed_tags = true
  propagate_tags          = "TASK_DEFINITION"

  tags = {
    Name        = "${var.project_name}-${var.environment}-worker-service"
    Environment = var.environment
  }
}

# ============================================================
# OUTPUTS
# ============================================================

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