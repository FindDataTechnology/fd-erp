# 账本备份恢复演练

判据不是"备份文件能解开"，而是**恢复出来的账与备份时点基线逐项一致**——尤其
`balance_fingerprint`（每科目每方向金额合计的 md5），它对上才说明每个科目的借贷余额都对。

## 为什么用一次性实例，不恢复进生产 postgres

`erp_ledger_app` 无建库权限；能建库的只有超级用户 `app`，而那要求把 admin 口令写进
清单。演练的价值不值得这个代价，所以用 `emptyDir` 起一个空的 postgres:16-alpine，
与生产库零连接。备份机取包 → 恢复进临时实例 → 重算 → 比对 → 删 Pod。

## 跑法

```bash
kubectl --context cheap-ts -n fd-prod apply -f fd-erp/deploy/drills/ledger-restore-drill.pod.yaml
kubectl --context cheap-ts -n fd-prod logs -f erp-ledger-restore-drill
kubectl --context cheap-ts -n fd-prod delete pod erp-ledger-restore-drill
```

最后一行日志必须是：

```
RESULT: PASS —— 恢复出的账与备份时点基线逐项一致
```

`INCONCLUSIVE` 不算过：说明 dump 恢复进去了但没有基线可比（基线缺失），
这时要回退到人工核对分录条数与借贷合计。

## 2026-11-11 首次演练记录

```
dump: /opt/backups/erp-ledger/erp-ledger-20261111-071839.dump（56983 字节，sha256 1f1d6e9a…）

指标                     恢复后                              备份时点
entries                  4                                   4
debit_total_base         100.000000                          100.000000
credit_total_base        100.000000                          100.000000
accounts                 12                                  12
proposals_confirmed      2                                   2
balance_fingerprint      6b060524466213006e6a4e1c9239056b    6b060524466213006e6a4e1c9239056b

RESULT: PASS
```

## 注意

- 演练取的是**异地副本**（备份机），不是本地 PVC —— 顺带验证了异地那份是可恢复的。
- 试点租户账本极小（4 笔分录），恢复只花几秒。量级上来后要重估临时实例的
  `resources`（现在 limits 1Gi）与超时。
- 演练不写入任何生产库；Pod 的 `restartPolicy: Never`，结束即 `Completed`。
