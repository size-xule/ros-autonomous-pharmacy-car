#!/usr/bin/env bash
# .21 比赛模式：自己发 WiFi（SSID NDKY / 10.211.121.21）
set -euo pipefail
[ -f /etc/netplan/99-wlan0-client.yaml ] && mv /etc/netplan/99-wlan0-client.yaml /etc/netplan/99-wlan0-client.yaml.disabled
netplan apply 2>/dev/null || true
systemctl disable --now hostapd 2>/dev/null || true
systemctl enable dnsmasq iscc-hotspot
systemctl restart iscc-hotspot
sleep 3
echo "== AP 状态 =="
ip -4 addr show wlan0 | grep inet || true
systemctl is-active iscc-hotspot dnsmasq
echo "== SSID: NDKY  密码: AP_PASSWORD_HERE  车 IP: 10.211.121.21 =="