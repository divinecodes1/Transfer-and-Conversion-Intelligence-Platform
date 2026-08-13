variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "prefix" {
  type    = string
  default = "ti"
  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.prefix))
    error_message = "prefix must be 2-8 lower-case alphanumeric characters starting with a letter."
  }
}

variable "environment" {
  type    = string
  default = "student"
}
