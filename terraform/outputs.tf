output "vpc_id" {
  value       = module.network.vpc_id
  description = "VPC created for the benchmark stack"
}

output "private_subnet_id" {
  value       = module.network.private_subnet_id
  description = "Primary private subnet used by EC2"
}

output "rds_endpoint" {
  value       = module.database.endpoint
  description = "RDS endpoint to use in PG_HOST"
}

output "rds_port" {
  value       = module.database.port
  description = "RDS port to use in PG_PORT"
}

output "ec2_instance_id" {
  value       = module.compute.instance_id
  description = "EC2 instance identifier"
}

output "ec2_private_ip" {
  value       = module.compute.private_ip
  description = "Private IP address of the application EC2 instance"
}

output "ssm_session_command" {
  value       = module.compute.ssm_session_command
  description = "Command to open an SSM session to the private EC2 instance"
}
