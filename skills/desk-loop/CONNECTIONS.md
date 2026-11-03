# 连接台账（防忘专用）

| 时间 | Agent 仓库 | 分支 | 台式机基座 | 说明 |
|---|---|---|---|---|
| 2026-10-30 | hukeying85-ux/JevHarness | `arena/03860148-jevharness` | `CGMD-Hub-Poll` @ DESKTOP-IEUDGS5（60 s 静默） | 首次打通：ping / 100 ps 烟测 / selfcheck 15-3-0 |
| 2026-10-30 | 同上 | 同上 | 同上 + `gmx` 工单 | 桌面 GPU 实测 Martini 3：1×12 布局 3323.2 ns/day（默认 4×12 只有 708.2） |
| 2026-11-02 | 同上 | 同上 | 同上 + `cgmd` 工单（`code/cgmd/desk_ops.py`） | 序列建模 + GPU MD：YLSLLQR 1309 珠 / 5.3 nm，2 ns @ 5400 ns/day |
| 2026-11-02 | 同上 | 同上 | 同上 | `skills/desk-loop`：request → wait → criteria → sync 闭环；100 ns 分片续算 |

> 新增一条：`python3 skills/desk-loop/deskloop.py ledger --append "<仓库>" --note "<说明>"`
