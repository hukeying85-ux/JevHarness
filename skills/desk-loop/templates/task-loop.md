# task-loop：把任务跑到成功

```
doctor  →  loop（request → wait → criteria）  →  sync（gate → commit → push → receipt）
```

规则：

1. **先 doctor**：分支不对就 `recover`；台式机不答就先 `status` 看 `queued` / 心跳。
2. **一个工单只回答一件事**：`cgmd` 的 `probe/ff/build/run` 分开发，回执里带着桌面侧绝对路径。
3. **只对「没回音」重试**：`fail` / `unsupported` 是真答案，重复发同一 payload 只会烧掉轮询周期。
4. **长任务切片**：`ns` 传**累计目标**（4 → 8 → 12），`resume=true` 从 `prod.cpt` 续算。
5. **判定靠文件，不靠感觉**：`success_criteria.json` 说过了才算过（`status=ok`、
   `performance_ns_per_day>0`、`final_report.finished=true`）。
6. **收尾必 sync**：`gate.py` 会拦轨迹文件/超大文件/分支不符；回执写到 `results/sync/last_sync.md`。
7. **失败就写清楚**：把工单号、桌面侧 workdir、`logs_tail` 原样写进 `results/sync/loop_receipt.md`。
