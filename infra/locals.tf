locals {
  # ── Naming ───────────────────────────────────────────────────────────────
  prefix = "cost-alloc"
  tags = {
    project     = "cost-allocator"
    environment = "prototype"
  }

  # ── Resource Group ───────────────────────────────────────────────────────
  rg_name = "rg-${local.prefix}"

  # ── VNet ─────────────────────────────────────────────────────────────────
  vnet_config = {
    name          = "vnet-${local.prefix}"
    address_space = ["10.0.0.0/8"]

    subnets = {
      snet-mgmt = {
        name             = "snet-mgmt"
        address_prefixes = ["10.0.0.0/24"]
      }
      snet-agw = {
        name             = "snet-agw"
        address_prefixes = ["10.0.1.0/24"]
      }
      AzureFirewallSubnet = {
        name             = "AzureFirewallSubnet"
        address_prefixes = ["10.0.2.0/26"]
      }
      snet-tenant-a = {
        name             = "snet-tenant-a"
        address_prefixes = ["10.100.1.0/24"]
        route_table = {
          name = "rt-tenant-a"
          routes = {
            default_via_fw = {
              name                   = "default-via-fw"
              address_prefix         = "0.0.0.0/0"
              next_hop_type          = "VirtualAppliance"
              next_hop_in_ip_address = local.firewall_private_ip
            }
          }
        }
      }
      snet-tenant-b = {
        name             = "snet-tenant-b"
        address_prefixes = ["10.100.2.0/24"]
        route_table = {
          name = "rt-tenant-b"
          routes = {
            default_via_fw = {
              name                   = "default-via-fw"
              address_prefix         = "0.0.0.0/0"
              next_hop_type          = "VirtualAppliance"
              next_hop_in_ip_address = local.firewall_private_ip
            }
          }
        }
      }
      snet-tenant-c = {
        name             = "snet-tenant-c"
        address_prefixes = ["10.100.3.0/24"]
        route_table = {
          name = "rt-tenant-c"
          routes = {
            default_via_fw = {
              name                   = "default-via-fw"
              address_prefix         = "0.0.0.0/0"
              next_hop_type          = "VirtualAppliance"
              next_hop_in_ip_address = local.firewall_private_ip
            }
          }
        }
      }
    }
  }

  # Azure Firewall gets first usable IP in its /26 subnet → .4 is first Azure-assignable
  # We know it deterministically: AzureFirewallSubnet = 10.0.2.0/26 → first non-reserved = 10.0.2.4
  firewall_private_ip = "10.0.2.4"

  # ── Log Analytics Workspace ───────────────────────────────────────────────
  law_config = {
    name      = "law-${local.prefix}"
    retention = 30
  }

  # ── Azure Firewall ────────────────────────────────────────────────────────
  fw_name    = "fw-${local.prefix}"
  fw_pip_name = "pip-fw-${local.prefix}"

  # ── Application Gateway ───────────────────────────────────────────────────
  agw_name     = "agw-${local.prefix}"
  agw_pip_name = "pip-agw-${local.prefix}"

  # Tenant VM IPs
  tenant_a_vm_ip = "10.100.1.10"
  tenant_b_vm_ip = "10.100.2.10"
  tenant_c_vm_ip = "10.100.3.10"

  # AGW hostnames
  agw_hostnames = {
    customer-a = "customer-a.oursharedapp.com"
    customer-b = "customer-b.oursharedapp.com"
    customer-c = "customer-c.oursharedapp.com"
  }

  # ── SQL ──────────────────────────────────────────────────────────────────
  sql_server_name = "sql-${local.prefix}"
  sql_databases = {
    customer-a = "db-tenant-customer-a"
    customer-b = "db-tenant-customer-b"
    customer-c = "db-tenant-customer-c"
  }

  # ── VMs ──────────────────────────────────────────────────────────────────
  vm_admin_username = "azureuser"
  vm_size           = "Standard_B2s"
  vm_image = {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  # cloud-init for each tenant VM
  cloud_init_tenant_a = <<-EOT
    #cloud-config
    package_update: true
    packages:
      - nginx
      - curl
    runcmd:
      - systemctl enable nginx
      - systemctl start nginx
      # Burst 300 requests on boot
      - for i in $(seq 1 300); do curl -sk https://example.com > /dev/null; done
  EOT

  cloud_init_tenant_b = <<-EOT
    #cloud-config
    package_update: true
    packages:
      - nginx
      - curl
    runcmd:
      - systemctl enable nginx
      - systemctl start nginx
    write_files:
      - path: /etc/cron.d/fw-traffic
        content: "*/2 * * * * root curl -s https://example.com > /dev/null\n"
        permissions: '0644'
  EOT

  cloud_init_tenant_c = <<-EOT
    #cloud-config
    package_update: true
    packages:
      - nginx
      - curl
    runcmd:
      - systemctl enable nginx
      - systemctl start nginx
    write_files:
      - path: /etc/cron.d/fw-traffic
        content: "*/5 * * * * root curl -s https://example.com > /dev/null\n"
        permissions: '0644'
  EOT
}
