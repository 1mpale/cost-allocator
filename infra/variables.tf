variable "subscription_id" {
  type        = string
  description = "Azure subscription ID"
}

variable "tenant_id" {
  type        = string
  description = "Azure tenant ID"
}

variable "location" {
  type        = string
  description = "Azure region"
  default     = "northeurope"
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key for VM admin user"
}
