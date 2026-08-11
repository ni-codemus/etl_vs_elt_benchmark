variable "aws_region" {
  description = "AWS region where the stack is created"
  type        = string
  default     = "eu-west-3"
}

variable "environment" {
  description = "Environment tag value"
  type        = string
}

variable "project_name" {
  description = "Base name used for AWS resources"
  type        = string
  default     = "bench-monitoring"
}

variable "availability_zone" {
  description = "Optional AZ override"
  type        = string
  default     = null
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.40.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR block for the public subnet used by the NAT gateway"
  type        = string
  default     = "10.40.0.0/24"
}

variable "private_subnet_cidr" {
  description = "CIDR block for the private subnet used by EC2 and RDS"
  type        = string
  default     = "10.40.1.0/24"
}

variable "private_subnet_secondary_cidr" {
  description = "CIDR block for the secondary private subnet used by the RDS subnet group"
  type        = string
  default     = "10.40.2.0/24"
}

variable "db_engine_version" {
  description = "PostgreSQL engine version"
  type        = string
  default     = "16.14"
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GiB for RDS"
  type        = number
  default     = 20
}

variable "ec2_instance_type" {
  description = "EC2 instance type for the application host"
  type        = string
  default     = "t3.small"
}

variable "ec2_root_volume_gb" {
  description = "Root volume size for the EC2 instance"
  type        = number
  default     = 30
}

variable "app_root" {
  description = "Installation directory on the EC2 instance"
  type        = string
  default     = "/opt/bench_monitoring"
}

variable "git_repository_url" {
  description = "Git repository URL to clone onto the EC2 instance"
  type        = string
  default     = ""
}

variable "git_repository_ref" {
  description = "Git branch, tag, or ref to deploy on the EC2 instance"
  type        = string
  default     = "main"
}

variable "pg_dbname" {
  description = "PostgreSQL database name"
  type        = string
  default     = "bench_db"
}

variable "pg_user" {
  description = "Application database user"
  type        = string
  default     = "bench_user"
}

variable "pg_password" {
  description = "Application database password"
  type        = string
  sensitive   = true
}

variable "pg_super_user" {
  description = "PostgreSQL master username"
  type        = string
  default     = "postgres"
}

variable "pg_super_pass" {
  description = "PostgreSQL master password"
  type        = string
  sensitive   = true
}

variable "pg_app_etl" {
  description = "PostgreSQL application_name used by ETL jobs"
  type        = string
  default     = "bench-etl"
}

variable "pg_app_elt" {
  description = "PostgreSQL application_name used by ELT jobs"
  type        = string
  default     = "bench-elt"
}

variable "s3_results_bucket" {
  description = "S3 bucket used to store benchmark series archives"
  type        = string
  default     = "my-tfstate-project1-nicode-202506"
}

variable "s3_results_key_prefix" {
  description = "S3 key prefix used for benchmark series archives"
  type        = string
  default     = "bench-monitor-series"
}

variable "tags" {
  description = "Common tags applied to all AWS resources"
  type        = map(string)
  default     = {}
}