variable "project_name" { type = string }
variable "environment" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "security_group_ids" { type = list(string) }
variable "node_type" { type = string }
variable "num_cache_nodes" { type = number }
variable "engine_version" { type = string }
variable "parameter_group_family" { type = string }
variable "at_rest_encryption" { type = bool }
variable "transit_encryption" { type = bool }
variable "auth_token" {
  type      = string
  sensitive = true
}
