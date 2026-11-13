#!/usr/bin/env bash
# READ-ONLY: pack systemd units (absolute-path safe)
set -u
export SSHPASS="${ROBOT_PASS:?export ROBOT_PASS first}"
H=keyuan22@10.211.121.22
SSH="sshpass -e ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 keyuan22@10.211.121.22"
OUT=/mnt/d/ISCC/_stage

echo "==== systemd 单元清单 ===="
$SSH "sudo -n sh -c 'cd / && find etc/systemd/system -maxdepth 2 -name \"*.service\" -type f | sort'"

echo "==== 打包 ===="
$SSH "sudo -n sh -c 'cd / && find etc/systemd/system -maxdepth 2 -name \"*.service\" -type f -print0 | tar czf - --null -T -'" > "$OUT/systemd.tgz"
echo "  -> $(du -h "$OUT/systemd.tgz" | cut -f1)"
tar tzf "$OUT/systemd.tgz" 2>/dev/null | head -40

echo "==== etc-home.tgz 顶层 ===="
tar tzf "$OUT/etc-home.tgz" 2>/dev/null | awk -F/ '{print $2"/"$3}' | sort -u | head -30
