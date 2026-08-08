data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["137112412989"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  name_prefix            = var.project_name
  common_tags            = var.tags
  s3_archive_bucket_arn  = "arn:aws:s3:::${var.s3_results_bucket}"
  s3_archive_objects_arn = "arn:aws:s3:::${var.s3_results_bucket}/${trim(var.s3_results_key_prefix, "/")}/*"
}

resource "aws_iam_role" "ec2" {
  name = "${local.name_prefix}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "s3_series_archive" {
  name = "${local.name_prefix}-s3-series-archive"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListSeriesArchiveBucket"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = local.s3_archive_bucket_arn
      },
      {
        Sid      = "ManageSeriesArchiveObjects"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:GetObject", "s3:HeadObject"]
        Resource = local.s3_archive_objects_arn
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${local.name_prefix}-ec2-profile"
  role = aws_iam_role.ec2.name
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.ec2_instance_type
  subnet_id                   = var.private_subnet_id
  vpc_security_group_ids      = [var.app_security_group_id]
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  associate_public_ip_address = false
  user_data = templatefile("${path.root}/bootstrap.sh.tpl", {
    app_root      = var.app_root
    repo_url      = var.git_repository_url
    repo_ref      = var.git_repository_ref
    pg_host       = var.db_host
    pg_port       = tostring(var.db_port)
    pg_dbname     = var.pg_dbname
    pg_user       = var.pg_user
    pg_password   = var.pg_password
    pg_super_user = var.pg_super_user
    pg_super_pass = var.pg_super_pass
    pg_app_etl    = var.pg_app_etl
    pg_app_elt    = var.pg_app_elt
  })
  user_data_replace_on_change = true

  root_block_device {
    volume_type = "gp3"
    volume_size = var.ec2_root_volume_gb
    encrypted   = true
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-app-ec2"
  })
}