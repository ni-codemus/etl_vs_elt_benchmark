variable "project_name" {
  type        = string
  description = "Base name used for AWS resources"
}

variable "environment" {
  type        = string
  description = "Environment tag value"
}

variable "ec2_instance_type" {
  type        = string
  description = "EC2 instance type for the application host"
}

variable "ec2_root_volume_gb" {
  type        = number
  description = "Root volume size for the EC2 instance"
}

variable "app_root" {
  type        = string
  description = "Installation directory on the EC2 instance"
}

variable "git_repository_url" {
  type        = string
  description = "Git repository URL to clone onto the EC2 instance"
}

variable "git_repository_ref" {
  type        = string
  description = "Git branch, tag, or ref to deploy on the EC2 instance"
}

variable "private_subnet_id" {
  type        = string
  description = "Private subnet used for the EC2 instance"
}

variable "app_security_group_id" {
  type        = string
  description = "Security group attached to the EC2 instance"
}

variable "db_host" {
  type        = string
  description = "RDS endpoint"
}

variable "db_port" {
  type        = number
  description = "RDS port"
}

variable "pg_dbname" {
  type        = string
  description = "PostgreSQL database name"
}

variable "pg_user" {
  type        = string
  description = "Application database user"
}

variable "pg_password" {
  type        = string
  description = "Application database password"
  sensitive   = true
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

variable "pg_app_etl" {
  type        = string
  description = "PostgreSQL application_name used by ETL jobs"
}

variable "pg_app_elt" {
  type        = string
  description = "PostgreSQL application_name used by ELT jobs"
}

variable "tags" {
  type        = map(string)
  description = "Common tags applied to all compute resources"
  default     = {}
}