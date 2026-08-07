variable "project_name" {
  type        = string
  description = "Base name used for AWS resources"
}

variable "environment" {
  type        = string
  description = "Environment tag value"
}

variable "vpc_id" {
  type        = string
  description = "VPC id used for the RDS security group"
}

variable "db_engine_version" {
  type        = string
  description = "PostgreSQL engine version"
}

variable "db_instance_class" {
  type        = string
  description = "RDS instance class"
}

variable "db_allocated_storage" {
  type        = number
  description = "Allocated storage in GiB for RDS"
}

variable "pg_dbname" {
  type        = string
  description = "PostgreSQL database name"
}

variable "pg_super_user" {
  type        = string
  description = "PostgreSQL master username"
}

variable "pg_super_pass" {
  type        = string
  description = "PostgreSQL master password"
  sensitive   = true
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnet ids used by the RDS subnet group"
}

variable "app_security_group_id" {
  type        = string
  description = "Security group id allowed to reach PostgreSQL"
}

variable "tags" {
  type        = map(string)
  description = "Common tags applied to all database resources"
  default     = {}
}