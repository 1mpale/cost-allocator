output "law_workspace_id" {
  description = "Resource ID of the Log Analytics Workspace"
  value       = module.law.workspace.id
}

output "agw_public_ip" {
  description = "Public IP address of the Application Gateway"
  value       = azurerm_public_ip.agw.ip_address
}

output "sql_server_fqdn" {
  description = "Fully qualified domain name of the SQL Server"
  value       = azurerm_mssql_server.sql.fully_qualified_domain_name
}

output "sql_admin_password" {
  description = "SQL Server admin password (sensitive)"
  value       = random_password.sql_admin.result
  sensitive   = true
}

output "firewall_private_ip" {
  description = "Private IP address of the Azure Firewall"
  value       = azurerm_firewall.fw.ip_configuration[0].private_ip_address
}
