variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix for resource naming"
  type        = string
  default     = "titanic"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}
