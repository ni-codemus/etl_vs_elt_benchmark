variable "aws_region" {
  type    = string
  default = "eu-west-3"
}

variable "environment" {
  type = string
}

variable "project_name" {
  type    = string
  default = "bench-monitoring"
}

variable "availability_zone" {
  type    = string
  default = null
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "public_subnet_cidr" {
  type    = string
  default = "10.40.0.0/24"
}

variable "private_subnet_cidr" {
  type    = string
  default = "10.40.1.0/24"
}

variable "private_subnet_secondary_cidr" {
  type    = string
  default = "10.40.2.0/24"
}

variable "db_engine_version" {
  type    = string
  default = "16.14"
}

variable "db_instance_class" {
  type    = string
  default = "db.m6g.large"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "ec2_instance_type" {
  type    = string
  default = "m6i.xlarge"
}

variable "ec2_root_volume_gb" {
  type    = number
  default = 30
}

variable "app_root" {
  type    = string
  default = "/opt/bench_monitoring"
}

variable "git_repository_url" {
  type    = string
  default = ""
}

variable "git_repository_ref" {
  type    = string
  default = "main"
}

variable "pg_dbname" {
  type    = string
  default = "bench_db"
}

variable "pg_user" {
  type    = string
  default = "bench_user"
}

variable "pg_password" {
  type      = string
  sensitive = true
}

variable "pg_super_user" {
  type    = string
  default = "postgres"
}

variable "pg_super_pass" {
  type      = string
  sensitive = true
}

variable "pg_app_etl" {
  type    = string
  default = "bench-etl"
}

variable "pg_app_elt" {
  type    = string
  default = "bench-elt"
}

variable "s3_results_bucket" {
  type    = string
  default = "my-tfstate-project1-nicode-202506"
}

variable "s3_results_key_prefix" {
  type    = string
  default = "bench-monitor-series/ec2-xlarge-rds-large"
}

variable "tags" {
  type    = map(string)
  default = {}
}