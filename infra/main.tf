# ── Random password for SQL ───────────────────────────────────────────────
resource "random_password" "sql_admin" {
  length           = 20
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
  min_upper        = 2
  min_lower        = 2
  min_numeric      = 2
  min_special      = 2
}

# ── Resource Group ────────────────────────────────────────────────────────
module "rg" {
  source  = "cloudnationhq/rg/azure"
  version = "~> 2.7"

  location = var.location
  tags     = local.tags

  groups = {
    main = {
      name     = local.rg_name
      location = var.location
    }
  }
}

# ── Log Analytics Workspace ───────────────────────────────────────────────
module "law" {
  source  = "cloudnationhq/law/azure"
  version = "~> 3.5"

  location            = var.location
  resource_group_name = module.rg.groups.main.name
  tags                = local.tags

  workspace = {
    name      = local.law_config.name
    retention = local.law_config.retention
  }
}

# ── Virtual Network ───────────────────────────────────────────────────────
module "vnet" {
  source  = "cloudnationhq/vnet/azure"
  version = "~> 9.7"

  location            = var.location
  resource_group_name = module.rg.groups.main.name
  tags                = local.tags

  vnet = local.vnet_config
}

# ── Azure Firewall Public IP ──────────────────────────────────────────────
resource "azurerm_public_ip" "fw" {
  name                = local.fw_pip_name
  location            = var.location
  resource_group_name = module.rg.groups.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

# ── Azure Firewall ────────────────────────────────────────────────────────
resource "azurerm_firewall" "fw" {
  name                = local.fw_name
  location            = var.location
  resource_group_name = module.rg.groups.main.name
  sku_name            = "AZFW_VNet"
  sku_tier            = "Standard"
  tags                = local.tags

  ip_configuration {
    name                 = "fw-ipconfig"
    subnet_id            = module.vnet.subnets["AzureFirewallSubnet"].id
    public_ip_address_id = azurerm_public_ip.fw.id
  }
}

# ── Firewall Network Rule Collection ─────────────────────────────────────
resource "azurerm_firewall_network_rule_collection" "tenant_egress" {
  name                = "tenant-egress"
  azure_firewall_name = azurerm_firewall.fw.name
  resource_group_name = module.rg.groups.main.name
  priority            = 200
  action              = "Allow"

  rule {
    name                  = "allow-tenant-http-https"
    source_addresses      = ["10.100.0.0/16"]
    destination_addresses = ["*"]
    destination_ports     = ["80", "443"]
    protocols             = ["TCP"]
  }
}

# ── Firewall Diagnostic Settings → LAW ───────────────────────────────────
resource "azurerm_monitor_diagnostic_setting" "fw" {
  name                       = "diag-fw"
  target_resource_id         = azurerm_firewall.fw.id
  log_analytics_workspace_id = module.law.workspace.id

  enabled_log {
    category = "AzureFirewallNetworkRule"
  }

  enabled_log {
    category = "AzureFirewallApplicationRule"
  }
}

# ── Application Gateway Public IP ─────────────────────────────────────────
resource "azurerm_public_ip" "agw" {
  name                = local.agw_pip_name
  location            = var.location
  resource_group_name = module.rg.groups.main.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.tags
}

# ── Application Gateway ───────────────────────────────────────────────────
resource "azurerm_application_gateway" "agw" {
  name                = local.agw_name
  location            = var.location
  resource_group_name = module.rg.groups.main.name
  tags                = local.tags

  sku {
    name = "Standard_v2"
    tier = "Standard_v2"
  }

  autoscale_configuration {
    min_capacity = 0
    max_capacity = 2
  }

  gateway_ip_configuration {
    name      = "agw-ipconfig"
    subnet_id = module.vnet.subnets["snet-agw"].id
  }

  frontend_port {
    name = "port-80"
    port = 80
  }

  frontend_ip_configuration {
    name                 = "agw-frontend-ip"
    public_ip_address_id = azurerm_public_ip.agw.id
  }

  # ── Backend pools ──────────────────────────────────────────────────────
  backend_address_pool {
    name         = "pool-customer-a"
    ip_addresses = [local.tenant_a_vm_ip]
  }

  backend_address_pool {
    name         = "pool-customer-b"
    ip_addresses = [local.tenant_b_vm_ip]
  }

  backend_address_pool {
    name         = "pool-customer-c"
    ip_addresses = [local.tenant_c_vm_ip]
  }

  # ── Backend HTTP settings ──────────────────────────────────────────────
  backend_http_settings {
    name                  = "http-settings"
    cookie_based_affinity = "Disabled"
    port                  = 80
    protocol              = "Http"
    request_timeout       = 30
  }

  # ── HTTP listeners ─────────────────────────────────────────────────────
  http_listener {
    name                           = "listener-customer-a"
    frontend_ip_configuration_name = "agw-frontend-ip"
    frontend_port_name             = "port-80"
    protocol                       = "Http"
    host_name                      = local.agw_hostnames["customer-a"]
  }

  http_listener {
    name                           = "listener-customer-b"
    frontend_ip_configuration_name = "agw-frontend-ip"
    frontend_port_name             = "port-80"
    protocol                       = "Http"
    host_name                      = local.agw_hostnames["customer-b"]
  }

  http_listener {
    name                           = "listener-customer-c"
    frontend_ip_configuration_name = "agw-frontend-ip"
    frontend_port_name             = "port-80"
    protocol                       = "Http"
    host_name                      = local.agw_hostnames["customer-c"]
  }

  # ── Routing rules ──────────────────────────────────────────────────────
  request_routing_rule {
    name                       = "rule-customer-a"
    rule_type                  = "Basic"
    priority                   = 100
    http_listener_name         = "listener-customer-a"
    backend_address_pool_name  = "pool-customer-a"
    backend_http_settings_name = "http-settings"
  }

  request_routing_rule {
    name                       = "rule-customer-b"
    rule_type                  = "Basic"
    priority                   = 110
    http_listener_name         = "listener-customer-b"
    backend_address_pool_name  = "pool-customer-b"
    backend_http_settings_name = "http-settings"
  }

  request_routing_rule {
    name                       = "rule-customer-c"
    rule_type                  = "Basic"
    priority                   = 120
    http_listener_name         = "listener-customer-c"
    backend_address_pool_name  = "pool-customer-c"
    backend_http_settings_name = "http-settings"
  }
}

# ── AGW Diagnostic Settings → LAW ────────────────────────────────────────
resource "azurerm_monitor_diagnostic_setting" "agw" {
  name                       = "diag-agw"
  target_resource_id         = azurerm_application_gateway.agw.id
  log_analytics_workspace_id = module.law.workspace.id

  enabled_log {
    category = "ApplicationGatewayAccessLog"
  }
}

# ── SQL Server ────────────────────────────────────────────────────────────
resource "azurerm_mssql_server" "sql" {
  name                         = local.sql_server_name
  resource_group_name          = module.rg.groups.main.name
  location                     = var.location
  version                      = "12.0"
  administrator_login          = "sqladmin"
  administrator_login_password = random_password.sql_admin.result
  tags                         = local.tags
}

resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_mssql_firewall_rule" "all" {
  name             = "AllowAll"
  server_id        = azurerm_mssql_server.sql.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "255.255.255.255"
}

# ── SQL Databases ─────────────────────────────────────────────────────────
resource "azurerm_mssql_database" "dbs" {
  for_each = local.sql_databases

  name      = each.value
  server_id = azurerm_mssql_server.sql.id
  collation = "SQL_Latin1_General_CP1_CI_AS"
  sku_name  = "GP_S_Gen5_1"

  auto_pause_delay_in_minutes = 120
  min_capacity                = 0.5
  tags                        = local.tags
}

# ── Network Interface Cards for VMs ──────────────────────────────────────
resource "azurerm_network_interface" "vm" {
  for_each = {
    tenant-a = {
      subnet_id  = module.vnet.subnets["snet-tenant-a"].id
      private_ip = local.tenant_a_vm_ip
    }
    tenant-b = {
      subnet_id  = module.vnet.subnets["snet-tenant-b"].id
      private_ip = local.tenant_b_vm_ip
    }
    tenant-c = {
      subnet_id  = module.vnet.subnets["snet-tenant-c"].id
      private_ip = local.tenant_c_vm_ip
    }
  }

  name                = "nic-vm-${each.key}"
  location            = var.location
  resource_group_name = module.rg.groups.main.name
  tags                = local.tags

  ip_configuration {
    name                          = "ipconfig"
    subnet_id                     = each.value.subnet_id
    private_ip_address_allocation = "Static"
    private_ip_address            = each.value.private_ip
  }
}

# ── Linux VMs ─────────────────────────────────────────────────────────────
resource "azurerm_linux_virtual_machine" "vms" {
  for_each = {
    tenant-a = {
      nic_id      = azurerm_network_interface.vm["tenant-a"].id
      custom_data = base64encode(local.cloud_init_tenant_a)
    }
    tenant-b = {
      nic_id      = azurerm_network_interface.vm["tenant-b"].id
      custom_data = base64encode(local.cloud_init_tenant_b)
    }
    tenant-c = {
      nic_id      = azurerm_network_interface.vm["tenant-c"].id
      custom_data = base64encode(local.cloud_init_tenant_c)
    }
  }

  name                  = "vm-${each.key}"
  location              = var.location
  resource_group_name   = module.rg.groups.main.name
  size                  = local.vm_size
  admin_username        = local.vm_admin_username
  network_interface_ids = [each.value.nic_id]
  custom_data           = each.value.custom_data
  tags                  = local.tags

  admin_ssh_key {
    username   = local.vm_admin_username
    public_key = var.ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = local.vm_image.publisher
    offer     = local.vm_image.offer
    sku       = local.vm_image.sku
    version   = local.vm_image.version
  }
}
