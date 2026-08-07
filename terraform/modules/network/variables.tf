variable "project_name" {
  type        = string
  description = "Base name used for AWS resources"
}

variable "environment" {
  type        = string
  description = "Environment tag value"
}

variable "availability_zone" {
  type        = string
  description = "Optional AZ override"
  default     = null
}

variable "vpc_cidr" {
  type        = string
  description = "CIDR block for the VPC"
}

variable "public_subnet_cidr" {
  type        = string
  description = "CIDR block for the public subnet used by the NAT gateway"
}

variable "private_subnet_cidr" {
  type        = string
  description = "CIDR block for the private subnet used by EC2"
}

variable "private_subnet_secondary_cidr" {
  type        = string
  description = "CIDR block for the secondary private subnet used by RDS"
}

variable "tags" {
  type        = map(string)
  description = "Common tags applied to all network resources"
  default     = {}
}