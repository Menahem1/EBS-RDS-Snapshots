
data "archive_file" "init_rds" {
  type        = "zip"
  source_dir  = "${path.module}/code_rds/"
  output_path = "${path.module}/lambda_rds_snapshot.zip"
}

resource "aws_iam_role" "iam_for_lambda_rds" {
  name = "lambda_rds_snapshot"

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

resource "aws_lambda_function" "rds_snapshot_lambda" {
  filename         = "${data.archive_file.init_rds.output_path}"
  function_name    = "rds_snapshot_scheduler"
  role             = "${aws_iam_role.iam_for_lambda_rds.arn}"
  handler          = "rds-snapshot-scheduler.lambda_handler"
  source_code_hash = "${data.archive_file.init_rds.output_base64sha256}"
  runtime          = "python3.6"
  timeout	   = "300"

  environment {
    variables = {
      history_table_name     = "${aws_dynamodb_table.snap-rds-dynamodb-table.name}"
      default_snapshot_time  = "${var.rds_snapshot_time}"
      custom_tag_name        = "${var.rds_custom_tag_name}"
      default_retention_days = "${var.rds_retention_days}"
      auto_snapshot_deletion = "${var.rds_snapshot_deletion}"
      default_time_zone      = "${var.rds_time_zone}"
      default_days_active    = "${var.rds_days_active}"
    }
  }
}


resource "aws_cloudwatch_event_target" "rds_snapshot_every_five_minutes" {
    rule = "${aws_cloudwatch_event_rule.every_five_minutes.name}"
    target_id = "rds_snapshot"
    arn = "${aws_lambda_function.rds_snapshot_lambda.arn}"
}

resource "aws_lambda_permission" "allow_cloudwatch_to_call_check_rds_snapshot" {
    statement_id = "AllowExecutionFromCloudWatch"
    action = "lambda:InvokeFunction"
    function_name = "${aws_lambda_function.rds_snapshot_lambda.function_name}"
    principal = "events.amazonaws.com"
    source_arn = "${aws_cloudwatch_event_rule.every_five_minutes.arn}"
}

resource "aws_iam_role_policy" "policy_rds" {
  name = "policy-rds-scheduler"
  role = "${aws_iam_role.iam_for_lambda_rds.id}"

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
			"Resource": "arn:aws:dynamodb:${var.region}:${data.aws_caller_identity.current.account_id}:table/${aws_dynamodb_table.snap-rds-dynamodb-table.name}"
		},
		{
			"Effect": "Allow",
			"Action": [
				"rds:CreateDBSnapshot",
				"rds:CreateDBClusterSnapshot",
				"rds:DeleteDBSnapshot",
				"rds:DeleteDBClusterSnapshot",
				"rds:DescribeDBSnapshots",
				"rds:DescribeDBClusterSnapshots",
				"rds:ListTagsForResource",
				"ec2:DescribeRegions",
				"rds:DescribeDBInstances"
			],
			"Resource": "*"
		}
	]
}
EOF
}

resource "aws_dynamodb_table" "snap-rds-dynamodb-table" {
  name           = "Scheduler-RDS-Snapshot-History"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "snapshot_id"

  attribute {
    name = "snapshot_id"
    type = "S"
  }

  tags {
    Name        = "Scheduler-RDS-Snapshot-History"
    Environment = "production"
  }
}

