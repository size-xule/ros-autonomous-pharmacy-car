#!/usr/bin/env bash
# .21 平时模式：连 OnePlusAce5（与 .22 同一热点），静态 10.211.121.21
set -euo pipefail
systemctl disable --now iscc-hotspot 2>/dev/null || true
systemctl disable --now hostapd 2>/dev/null || true
systemctl disable --now dnsmasq 2>/dev/null || true
ip link set wlan0 down 2>/dev/null || true
ip addr flush dev wlan0 2>/dev/null || true
cat > /etc/netplan/99-wlan0-client.yaml <<'EOF'
network:
  version: 2
  renderer: networkd
  wifis:
    wlan0:
      dhcp4: false
      dhcp6: false
      addresses: [10.211.121.21/24]
      routes:
        - to: default
          via: 10.211.121.1
      nameservers:
        addresses: [114.114.114.114, 223.5.5.5]
      access-points:
        "OnePlusAce5":
          password: "WIFI_PASSWORD_HERE"
EOF
chmod 600 /etc/netplan/99-wlan0-client.yaml
netplan apply
sleep 6
echo "== 客户端模式 =="
ip -4 addr show wlan0 | grep inet || echo "!! 未连上，检查 OnePlusAce5 热点"