# ALB Module Outputs

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