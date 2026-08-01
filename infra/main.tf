##############################################################################
# Session 14 — Infrastructure as code.
#
# Provisions the Azure side of the lakehouse: a resource group, an ADLS Gen2
# storage account, and one container per medallion layer.
#
#   terraform init
#   terraform plan
#   terraform apply
#   terraform destroy      <- teardown is part of the design, not an afterthought
#
# NOTE: not applied against a live subscription yet — no Azure account is
# attached to this project. The config is written, validated and reviewable;
# `terraform apply` is the remaining step.
##############################################################################

terraform {
  required_version = ">= 1.5"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "project" {
  type        = string
  default     = "ausdatajobsradar"
  description = "Lowercase, no dashes — Azure storage account names are restrictive."
}

variable "location" {
  type        = string
  default     = "australiaeast"
  description = "Keep data in-region: the source data is Australian job ads."
}

variable "monthly_budget_aud" {
  type        = number
  default     = 10
  description = "Budget alert threshold. This project is designed to run near $0."
}

resource "azurerm_resource_group" "radar" {
  name     = "rg-${var.project}"
  location = var.location

  tags = {
    project    = "aus-data-jobs-radar"
    managed_by = "terraform"
  }
}

# ADLS Gen2 = a storage account with hierarchical namespace enabled.
# Without is_hns_enabled it is flat blob storage and directory operations
# (which the medallion layout depends on) become expensive.
resource "azurerm_storage_account" "lake" {
  name                     = "st${var.project}"
  resource_group_name      = azurerm_resource_group.radar.name
  location                 = azurerm_resource_group.radar.location
  account_tier             = "Standard"
  account_replication_type = "LRS" # cheapest; this data is reproducible from source
  is_hns_enabled           = true

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  blob_properties {
    delete_retention_policy {
      days = 7
    }
  }

  tags = azurerm_resource_group.radar.tags
}

# One container per medallion layer, so access can be scoped per layer later.
resource "azurerm_storage_container" "layers" {
  for_each = toset(["bronze", "silver", "gold"])

  name                  = each.key
  storage_account_name  = azurerm_storage_account.lake.name
  container_access_type = "private"
}

# Secrets live in Key Vault, never in the repo — same rule as .env locally.
resource "azurerm_key_vault" "secrets" {
  name                       = "kv-${var.project}"
  location                   = azurerm_resource_group.radar.location
  resource_group_name        = azurerm_resource_group.radar.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # allows clean `terraform destroy` in dev

  tags = azurerm_resource_group.radar.tags
}

data "azurerm_client_config" "current" {}

# Cost guardrail: alert at 80% and 100% of a deliberately tiny budget.
resource "azurerm_consumption_budget_resource_group" "guard" {
  name              = "budget-${var.project}"
  resource_group_id = azurerm_resource_group.radar.id

  amount     = var.monthly_budget_aud
  time_grain = "Monthly"

  time_period {
    start_date = formatdate("YYYY-MM-01'T'00:00:00Z", timestamp())
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    contact_emails = ["didikol777@gmail.com"]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    contact_emails = ["didikol777@gmail.com"]
  }

  lifecycle {
    ignore_changes = [time_period] # timestamp() would force a diff every plan
  }
}

output "storage_account_name" {
  value = azurerm_storage_account.lake.name
}

output "container_urls" {
  value = {
    for layer, container in azurerm_storage_container.layers :
    layer => "abfss://${container.name}@${azurerm_storage_account.lake.name}.dfs.core.windows.net/"
  }
}
