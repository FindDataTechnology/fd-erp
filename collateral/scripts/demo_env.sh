#!/bin/bash
# ERP 演示环境 bring-up（一次性）：
#   1) port-forward 演示库（postgres pod → 127.0.0.1:30440）
#   2) 拉起两个内核进程（一进程一租户）：
#      8301 = demo-crossborder（跨境电商） 8302 = demo-restaurant（餐饮连锁）
#   3) 为跨境租户做 fx 种子（USD 汇率，出处 ecb-exr）
# 口令只从 secrets/erp-demo.env 读，本脚本不打印任何凭据。
set -euo pipefail
# 仓根**先算**（本文件在 fd-erp/collateral/scripts/ ⇒ 上四级是 finddata），算不出或算错
# （目标里没有内核仓）才退回写死的绝对路径。
# 2026-11-16 搬进 `fd-erp/collateral/` 时修：原版第 9 行算完、第 10 行又无条件覆盖成
# 硬编码值 ⇒ 那行计算是死代码，深度改了对它没影响，而换台机就静默走错。
_guess="$(cd "$(dirname "$0")/../../../.." 2>/dev/null && pwd || true)"
if [ -n "$_guess" ] && [ -d "$_guess/fd-erp-ledger-mcp" ]; then
  FINDATA="$_guess"
else
  FINDATA="/Users/chengsishi/finddata"
fi
KERNEL="$FINDATA/fd-erp-ledger-mcp"
ENV_FILE="$FINDATA/secrets/erp-demo.env"

# 1) port-forward（幂等）
if ! nc -z -w 2 127.0.0.1 30440 2>/dev/null; then
  kubectl --context cheap-ts -n postgres port-forward svc/postgres 30440:5432 \
    > /tmp/erp-demo-pf.log 2>&1 &
  sleep 3
fi
echo "[1/3] port-forward 30440 -> postgres pod: $(nc -z -w 2 127.0.0.1 30440 && echo up || echo FAIL)"

DSN=$(grep '^ERP_LEDGER_DATABASE_URL=' "$ENV_FILE" | cut -d= -f2-)

# 2) 两个内核进程（幂等：端口已被占即视为已在跑）
start_kernel() {
  local port=$1 tenant=$2
  if nc -z -w 2 127.0.0.1 "$port" 2>/dev/null; then
    echo "[2/3] kernel $tenant :$port already up"
    return
  fi
  (cd "$KERNEL" && \
   ERP_LEDGER_DATABASE_URL="$DSN" ERP_TENANT_ID="$tenant" \
   nohup .venv/bin/fd-erp-ledger-mcp serve --host 127.0.0.1 --port "$port" \
     > "/tmp/erp-demo-kernel-$tenant.log" 2>&1 < /dev/null &)
  sleep 4
  echo "[2/3] kernel $tenant :$port $(nc -z -w 2 127.0.0.1 "$port" && echo up || echo FAIL)"
}
start_kernel 8301 demo-crossborder
start_kernel 8302 demo-restaurant

# 3) fx 种子（跨境租户需要 USD 汇率出处；幂等）
export ERP_LEDGER_DATABASE_URL="$DSN"
export ERP_TENANT_ID=demo-crossborder
echo "[3/3] seed-fx (demo-crossborder):"
(cd "$KERNEL" && .venv/bin/fd-erp-ledger-mcp seed-fx "$FINDATA/fd-erp/collateral/datasets/fx-usd-demo.json" 2>/dev/null || echo "(fx 已种或跳过)")

echo
echo "bring-up 完成：跨境演示 = fd-erp/collateral/scripts/demo_crossborder.py"
echo "              餐饮演示 = fd-erp/collateral/scripts/demo_restaurant.py"
