terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "benchmark" {
  source = "../../stacks/benchmark"

  aws_region                    = var.aws_region
  environment                   = var.environment
  project_name                  = var.project_name
  availability_zone             = var.availability_zone
  vpc_cidr                      = var.vpc_cidr
  public_subnet_cidr            = var.public_subnet_cidr
  private_subnet_cidr           = var.private_subnet_cidr
  private_subnet_secondary_cidr = var.private_subnet_secondary_cidr
  db_engine_version             = var.db_engine_version
  db_instance_class             = var.db_instance_class
  db_allocated_storage          = var.db_allocated_storage
  ec2_instance_type             = var.ec2_instance_type
  ec2_root_volume_gb            = var.ec2_root_volume_gb
  app_root                      = var.app_root
  git_repository_url            = var.git_repository_url
  git_repository_ref            = var.git_repository_ref
  pg_dbname                     = var.pg_dbname
  pg_user                       = var.pg_user
  pg_password                   = var.pg_password
  pg_super_user                 = var.pg_super_user
  pg_super_pass                 = var.pg_super_pass
  pg_app_etl                    = var.pg_app_etl
  pg_app_elt                    = var.pg_app_elt
  s3_results_bucket             = var.s3_results_bucket
  s3_results_key_prefix         = var.s3_results_key_prefix
  tags                          = var.tags
}