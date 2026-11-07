# ALB Module for Campus Medical Assistance
# Creates Application Load Balancer with HTTPS listener

# ============================================================
# ALB
# ============================================================

resource "aws_lb" "main" {
  name               = "${var.project_name}-${var.environment}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = var.security_group_ids
  subnets            = var.public_subnet_ids
  enable_deletion_protection = true

  access_logs {
    bucket  = var.access_logs_bucket
    prefix  = "${var.project_name}-${var.environment}"
    enabled = var.access_logs_bucket != ""
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-alb"
    Environment = var.environment
  }
}

# ============================================================
# TARGET GROUP
# ============================================================

resource "aws_lb_target_group" "api" {
  name        = "${var.project_name}-${var.environment}-api"
  port        = var.target_group_config.port
  protocol    = var.target_group_config.protocol
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = var.target_group_config.health_check_path
    interval            = var.target_group_config.health_check_interval
    timeout             = var.target_group_config.health_check_timeout
    healthy_threshold   = var.target_group_config.healthy_threshold
    unhealthy_threshold = var.target_group_config.unhealthy_threshold
    matcher             = var.target_group_config.matcher
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-api-tg"
    Environment = var.environment
  }
}

# ============================================================
# HTTP LISTENER (redirect to HTTPS)
# ============================================================

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# ============================================================
# HTTPS LISTENER
# ============================================================

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ============================================================
# WAF (optional - basic protection)
# ============================================================

resource "aws_wafv2_web_acl" "main" {
  count = var.enable_waf ? 1 : 0
  name  = "${var.project_name}-${var.environment}-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "RateLimitRule"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitRule"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "SQLInjectionRule"
    priority = 2
    action {
      block {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesSQLiRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "SQLInjectionRule"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "XSSRule"
    priority = 3
    action {
      block {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesXSSRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "XSSRule"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-${var.environment}-waf"
    sampled_requests_enabled   = true
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-waf"
    Environment = var.environment
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  count = var.enable_waf ? 1 : 0
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

# ============================================================
# OUTPUTS
# ============================================================

output "alb_arn" {
  value       = aws_lb.main.arn
  description = "ALB ARN"
}

output "alb_dns_name" {
  value       = aws_lb.main.dns_name
  description = "ALB DNS Name"
}

output "alb_zone_id" {
  value       = aws_lb.main.zone_id
  description = "ALB Zone ID"
}

output "target_group_arns" {
  value       = [aws_lb_target_group.api.arn]
  description = "Target Group ARNs"
}

output "http_listener_arn" {
  value       = aws_lb_listener.http.arn
  description = "HTTP Listener ARN"
}

output "https_listener_arn" {
  value       = aws_lb_listener.https.arn
  description = "HTTPS Listener ARN"
}