output "vpc_id" {
  value = aws_vpc.this.id
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "private_subnet_id" {
  value = aws_subnet.private.id
}

output "private_subnet_secondary_id" {
  value = aws_subnet.private_secondary.id
}

output "app_security_group_id" {
  value = aws_security_group.ec2.id
}