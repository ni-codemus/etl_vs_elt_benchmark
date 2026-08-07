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

locals {
  common_tags = {
    Project     = var.project_name
    ManagedBy   = "terraform"
    Environment = var.environment
  }
}

module "network" {
  source = "./modules/network"

  project_name                  = var.project_name
  environment                   = var.environment
  availability_zone             = var.availability_zone
  vpc_cidr                      = var.vpc_cidr
  public_subnet_cidr            = var.public_subnet_cidr
  private_subnet_cidr           = var.private_subnet_cidr
  private_subnet_secondary_cidr = var.private_subnet_secondary_cidr
  tags                          = local.common_tags
}

module "database" {
  source = "./modules/database"

  project_name          = var.project_name
  environment           = var.environment
  vpc_id                = module.network.vpc_id
  db_engine_version     = var.db_engine_version
  db_instance_class     = var.db_instance_class
  db_allocated_storage  = var.db_allocated_storage
  pg_dbname             = var.pg_dbname
  pg_super_user         = var.pg_super_user
  pg_super_pass         = var.pg_super_pass
  private_subnet_ids    = [module.network.private_subnet_id, module.network.private_subnet_secondary_id]
  app_security_group_id = module.network.app_security_group_id
  tags                  = local.common_tags
}

module "compute" {
  source = "./modules/compute"

  project_name          = var.project_name
  environment           = var.environment
  ec2_instance_type     = var.ec2_instance_type
  ec2_root_volume_gb    = var.ec2_root_volume_gb
  app_root              = var.app_root
  git_repository_url    = var.git_repository_url
  git_repository_ref    = var.git_repository_ref
  private_subnet_id     = module.network.private_subnet_id
  app_security_group_id = module.network.app_security_group_id
  db_host               = module.database.endpoint
  db_port               = module.database.port
  pg_dbname             = var.pg_dbname
  pg_user               = var.pg_user
  pg_password           = var.pg_password
  pg_super_user         = var.pg_super_user
  pg_super_pass         = var.pg_super_pass
  pg_app_etl            = var.pg_app_etl
  pg_app_elt            = var.pg_app_elt
  tags                  = local.common_tags
}
