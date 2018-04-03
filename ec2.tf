terraform {
  backend "s3" {
    bucket = "terraform-states-engie-digital-noprod"
    key    = "snapshot-scheduler/poc.tfstate"
    region = "eu-west-1"
  }
}

variable "region" { default = "eu-west-1"}

provider "aws" {
  region = "${var.region}"
}

data "aws_caller_identity" "current" {}

data "archive_file" "init" {
  type        = "zip"
  source_dir  = "${path.module}/code_ec2/"
  output_path = "${path.module}/lambda_ec2_snapshot.zip"
}

resource "aws_iam_role" "iam_for_lambda" {
  name = "lambda_ebs_snapshot"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Effect": "Allow",
      "Sid": ""
    }
  ]
}
EOF
}

resource "aws_lambda_function" "ebs_snapshot_lambda" {
  filename         = "${data.archive_file.init.output_path}"
  function_name    = "ebs_snapshot_scheduler"
  role             = "${aws_iam_role.iam_for_lambda.arn}"
  handler          = "ebs-snapshot-scheduler.lambda_handler"
  source_code_hash = "${data.archive_file.init.output_base64sha256}"
  runtime          = "python3.6"
  timeout	   = "300"

  environment {
    variables = {
      history_table_name     = "${aws_dynamodb_table.snap-ebs-dynamodb-table.name}"
      default_snapshot_time  = "${var.ebs_snapshot_time}"
      custom_tag_name        = "${var.ebs_custom_tag_name}"
      default_retention_days = "${var.ebs_retention_days}"
      auto_snapshot_deletion = "${var.ebs_snapshot_deletion}"
      default_time_zone      = "${var.ebs_time_zone}"
      default_days_active    = "${var.ebs_days_active}"
    }
  }
}

resource "aws_cloudwatch_event_rule" "every_five_minutes" {
    name = "every-five-minutes"
    description = "Fires every five minutes"
    schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "ebs_snapshot_every_five_minutes" {
    rule = "${aws_cloudwatch_event_rule.every_five_minutes.name}"
    target_id = "ebs_snapshot"
    arn = "${aws_lambda_function.ebs_snapshot_lambda.arn}"
}

resource "aws_lambda_permission" "allow_cloudwatch_to_call_check_ebs_snapshot" {
    statement_id = "AllowExecutionFromCloudWatch"
    action = "lambda:InvokeFunction"
    function_name = "${aws_lambda_function.ebs_snapshot_lambda.function_name}"
    principal = "events.amazonaws.com"
    source_arn = "${aws_cloudwatch_event_rule.every_five_minutes.arn}"
}

resource "aws_iam_role_policy" "policy" {
  name = "policy-ebs-scheduler"
  role = "${aws_iam_role.iam_for_lambda.id}"

  policy = <<EOF
{
	"Version": "2012-10-17",
	"Statement": [{
			"Effect": "Allow",
			"Action": [
				"logs:CreateLogGroup",
				"logs:CreateLogStream",
				"logs:PutLogEvents"
			],
			"Resource": "arn:aws:logs:*:*:log-group:/aws/lambda/*"
		},
		{
			"Effect": "Allow",
			"Action": [
				"dynamodb:GetItem",
				"dynamodb:PutItem",
				"dynamodb:DeleteItem",
				"dynamodb:Scan"
			],
			"Resource": "arn:aws:dynamodb:${var.region}:${data.aws_caller_identity.current.account_id}:table/${aws_dynamodb_table.snap-ebs-dynamodb-table.name}"
		},
		{
			"Effect": "Allow",
			"Action": [
				"ec2:CreateSnapshot",
				"ec2:CreateTags",
				"ec2:DeleteSnapshot",
				"ec2:DescribeSnapshots",
				"ec2:DescribeTags",
				"ec2:DescribeRegions",
				"ec2:DescribeVolumes",
				"ec2:DescribeInstances"
			],
			"Resource": "*"
		}
	]
}
EOF
}

resource "aws_dynamodb_table" "snap-ebs-dynamodb-table" {
  name           = "Scheduler-EBS-Snapshot-History"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "snapshot_id"

  attribute {
    name = "snapshot_id"
    type = "S"
  }

  tags {
    Name        = "Scheduler-EBS-Snapshot-History"
    Environment = "production"
  }
}

