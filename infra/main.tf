terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Sufijo único para el bucket S3 (nombres globales únicos)
resource "random_id" "suffix" {
  byte_length = 4
}

# -----------------------------------------------------------------------------
# 1. DATA LAKE: S3 Bucket con cifrado SSE y ciclo de vida optimizado
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "energy_datalake" {
  bucket        = "${var.project_name}-lake-${random_id.suffix.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "block_public" {
  bucket                  = aws_s3_bucket.energy_datalake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datalake_crypto" {
  bucket = aws_s3_bucket.energy_datalake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "datalake_lifecycle" {
  bucket = aws_s3_bucket.energy_datalake.id

  rule {
    id     = "tiering-raw-telemetry"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }
  }
}

# -----------------------------------------------------------------------------
# 2. TIEMPO REAL: Tabla DynamoDB Serverless (Hot Path / On-Demand)
# -----------------------------------------------------------------------------
resource "aws_dynamodb_table" "islands_realtime" {
  name         = "CanariasEnergyRealtime"
  billing_mode = "PAY_PER_REQUEST" # Free-Tier friendly, sin costes fijos
  hash_key     = "island_id"       # Partition Key (PK)
  range_key    = "timestamp"       # Sort Key (SK)

  attribute {
    name = "island_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }
}

# -----------------------------------------------------------------------------
# 3. SEGURIDAD: Rol IAM de Mínimo Privilegio para Lambda
# -----------------------------------------------------------------------------
resource "aws_iam_role" "lambda_exec_role" {
  name = "${var.project_name}-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_least_privilege" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda_exec_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "S3DataLakePutAccess"
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "${aws_s3_bucket.energy_datalake.arn}/*"
      },
      {
        Sid      = "DynamoDBHotPathWriteAccess"
        Effect   = "Allow"
        Action   = ["dynamodb:BatchWriteItem", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.islands_realtime.arn
      },
      {
        Sid    = "CloudWatchLoggingAccess"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# 4. CÓMPUTO: Empaquetado automático y función AWS Lambda
# -----------------------------------------------------------------------------
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../src"
  output_path = "${path.module}/lambda_payload.zip"
}

resource "aws_lambda_function" "ingestor_lambda" {
  filename         = data.archive_file.lambda_zip.output_path
  function_name    = "${var.project_name}-ingestor"
  role             = aws_iam_role.lambda_exec_role.arn
  handler          = "lambda_function.lambda_handler"
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256
  runtime          = "python3.12"
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      S3_BUCKET_NAME      = aws_s3_bucket.energy_datalake.bucket
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.islands_realtime.name
    }
  }
}

# -----------------------------------------------------------------------------
# 5. ORQUESTACIÓN: Amazon EventBridge disparando cada 15 minutos
# -----------------------------------------------------------------------------
resource "aws_cloudwatch_event_rule" "every_15_mins" {
  name                = "${var.project_name}-every-15m"
  description         = "Dispara la ingesta energética y meteorológica de Canarias cada 15 min"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_cloudwatch_event_target" "trigger_lambda" {
  rule      = aws_cloudwatch_event_rule.every_15_mins.name
  target_id = "TriggerCanariasIngestor"
  arn       = aws_lambda_function.ingestor_lambda.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestor_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_15_mins.arn
}