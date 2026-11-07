# ECS Module for Campus Medical Assistance (API Service)
# Creates ECS cluster, service, task definition, and auto scaling

# ============================================================
# ECS CLUSTER
# ============================================================

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs_exec.name
      }
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-cluster"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_log_group" "ecs_exec" {
  name              = "/aws/ecs/${var.project_name}-${var.environment}-exec"
  retention_in_days = 30
}

# ============================================================
# CLOUDWATCH LOG GROUP FOR CONTAINER LOGS
# ============================================================

resource "aws_cloudwatch_log_group" "container" {
  name              = var.log_group_name
  retention_in_days = 30
}

# ============================================================
# TASK DEFINITION
# ============================================================

data "aws_iam_policy_document" "task_execution" {
  statement {
    actions = [
      "ecr:GetAuthorizationToken",
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "task_role" {
  statement {
    actions = [
      "secretsmanager:GetSecretValue",
      "ssm:GetParameters",
      "ssm:GetParameter",
      "s3:GetObject",
      "s3:PutObject",
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sns:Publish",
    ]
    resources = [
      "arn:aws:secretsmanager:${var.aws_region}:${var.account_id}:secret:emergency-response/*",
      "arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/emergency-response/*",
      "arn:aws:s3:::emergency-response-${var.environment}-*",
      "arn:aws:sqs:${var.aws_region}:${var.account_id}:emergency-response-*",
      "arn:aws:sns:${var.aws_region}:${var.account_id}:emergency-response-*",
    ]
  }

resource "aws_ecs_task_definition" "main" {
  family                   = "${var.project_name}-${var.environment}-api"
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
      name      = "${var.project_name}-api"
      image     = var.container_image
      essential = true
      portMappings = [{
        containerPort = 8000
        protocol      = "tcp"
      }]
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
        command  = ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
        interval = var.health_check_interval
        timeout  = var.health_check_timeout
        retries  = var.health_check_retries
        startPeriod = var.health_check_start_period
      }
      ulimits = [{
        name = "nofile"
        softLimit = 65536
        hardLimit = 65536
      }]
      readonlyRootFilesystem = false
      user = "appuser"
    }
  ])

  volumes = [{
    name = "uploads"
    efsVolumeConfiguration = {
      fileSystemId          = var.efs_file_system_id
      rootDirectory         = "/uploads"
      transitEncryption     = "ENABLED"
      authorizationConfig = {
        accessPointId = var.efs_access_point_id
        iam           = "ENABLED"
      }
    }
  }]

  tags = {
    Name        = "${var.project_name}-${var.environment}-api-task"
    Environment = var.environment
  }
}

# ============================================================
# SERVICE
# ============================================================

resource "aws_ecs_service" "main" {
  name            = "${var.project_name}-${var.environment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.main.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = var.security_group_ids
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.alb_target_group_arns[0]
    container_name   = "${var.project_name}-api"
    container_port   = 8000
  }

  deployment_controller {
    type = "ECS"
  }

  deployment_configuration {
    maximum_percent         = 200
    minimum_healthy_percent = 50
    deployment_circuit_breaker {
      enable   = true
      rollback = true
    }
  }

  enable_ecs_managed_tags = true
  propagate_tags          = "TASK_DEFINITION"

  tags = {
    Name        = "${var.project_name}-${var.environment}-api-service"
    Environment = var.environment
  }
}

# ============================================================
# SERVICE AUTO SCALING
# ============================================================

resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.main.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu_scale_up" {
  name               = "${var.project_name}-${var.environment}-api-cpu-scale-up"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 300
  }
}

resource "aws_appautoscaling_policy" "memory_scale_up" {
  name               = "${var.project_name}-${var.environment}-api-memory-scale-up"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 80.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    scale_in_cooldown  = 300
    scale_out_cooldown = 300
  }
}

# ============================================================
# OUTPUTS
# ============================================================

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