data "aws_caller_identity" "current" {}

# ECR repository for the Lambda container image
resource "aws_ecr_repository" "predictor" {
  name                 = "${var.project_name}-${var.environment}-predictor"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

# IAM role
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-${var.environment}-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "dynamodb_access" {
  name = "${var.project_name}-${var.environment}-dynamodb-access"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:UpdateItem",
        "dynamodb:Scan",
        "dynamodb:DeleteItem",
      ]
      Resource = aws_dynamodb_table.sobreviventes.arn
    }]
  })
}

# Build and push container image
resource "null_resource" "lambda_build" {
  triggers = {
    handler_hash       = filesha256("${path.module}/../lambda/handler.py")
    preprocessing_hash = filesha256("${path.module}/../lambda/preprocessing.py")
    requirements_hash  = filesha256("${path.module}/../lambda/requirements.txt")
    dockerfile_hash    = filesha256("${path.module}/../lambda/Dockerfile")
  }

  provisioner "local-exec" {
    command     = "bash scripts/build_and_push.sh ${aws_ecr_repository.predictor.repository_url}"
    working_dir = "${path.module}/.."
  }
}

# Lambda function
resource "aws_lambda_function" "predictor" {
  depends_on = [null_resource.lambda_build]

  function_name = "${var.project_name}-${var.environment}-predictor"
  role          = aws_iam_role.lambda_exec.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.predictor.repository_url}:latest"
  timeout       = 30
  memory_size   = 1024

  environment {
    variables = {
      DYNAMODB_TABLE = aws_dynamodb_table.sobreviventes.name
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
