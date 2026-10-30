# `cgmd` 落地后要发的单子（目标：100 ns 粗粒化生产）

前置：`cgmd` kind 已合进 `arena/32cd826e-0fuye`（见 `README.md`）。客户端仍是只读的 0fuye 克隆 +
本仓（JevHarness）自己的 `hub/mailbox`：

```bash
git clone -b arena/32cd826e-0fuye https://github.com/hukeying85-ux/0fuye.git /tmp/0fuye
```

> 单条信箱任务的硬上限是 `MaxJobSeconds = 3600`（1 h）。100 ns 会超过它，所以生产按 **1 h 一格**跑，
> 每格靠 `prod.cpt` 续跑（`resume: true`）—— 不会从零重来，也不会丢轨迹。

## 第 1 单 · 环境清点（几秒）

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "probe", "roots": ["F:\\0wsh\\asd", "F:\\0wsh", "F:\\"]}' \
  --read-repo /tmp/0fuye --timeout 600
```

看 `detail.ops.detail`：`pythons[0]`（`version` ≥ 3.8 才装得了 vermouth；本模型不需要 vermouth，`pip` 有就行）、
`gmx.version`、`martini.file`。

## 第 2 单 · 拿 Martini 3 力场（不入库，只落台式机）

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "ff", "python": "<第1单挑中的解释器绝对路径>", "install_timeout": 900}' \
  --read-repo /tmp/0fuye --timeout 1200
```

`pip install martini-forcefields`；失败自动退回 `codeload.github.com/marrink-lab/martini-forcefields`
下载解包到 `%USERPROFILE%\cgmd-runs\martini3`。

## 第 3 单 · 找肽 + 建体系 + 开工（100 ns，第一格）

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "all", "roots": ["F:\\0wsh\\asd", "F:\\0wsh", "F:\\"],
                "days": 120, "depth": 4, "box_nm": 6.0,
                "ns": 100.0, "gpu_id": 0, "timeout_s": 3600, "prod_timeout": 3000,
                "fallback_sequence": "KLVFFAE"}' \
  --read-repo /tmp/0fuye --timeout 3600
```

这一单做四件事：`search`（按 mtime 从新到旧列候选，并从 `.gro` 残基名还原序列）→ `build`（6 nm 盒、
约 1.7k 珠子）→ EM → 200 ps NPT → 生产第一格（≤ 1 h）。回执里有 `detail.ops.detail.report`。

## 第 4 单 · 续跑（每格一单，直到 `prod.log` 出现 `Finished mdrun`）

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "run", "workdir": "<第3单 detail.ops.detail.system 里的目录>",
                "ns": 100.0, "resume": true, "gpu_id": 0,
                "timeout_s": 3600, "prod_timeout": 3000}' \
  --read-repo /tmp/0fuye --timeout 3600
```

`resume: true` 且 `prod.cpt` 存在时，`mdrun` 走 `-cpi prod.cpt -append`：从检查点接着算，`prod.xtc` 续写。
一直重复到回执 `...report.finished == true`。

## 回执里要核对的字段

| 字段 | 期望 |
| --- | --- |
| `result.status` | `ok` |
| `...detail.ops.detail.report.accelerator` | `gpu` |
| `...report.performance_ns_per_day` | > 0（CG 体系应远高于全原子烟测的 617） |
| `...report.finished` | `true`（只有第 4 单的最后一格才会是 true） |
| `...report.steps_requested` | 5,000,000（= 100 ns ÷ 0.02 ps） |
| `...report.structure.final.peptide_beads` | == 残基数 |
| `...stages[]` 的 `returncode` | 全 0；最后一格 `mdrun-prod-gpu.resumed == true` |
| `...detail.system.sequence` | 从 F 盘还原的那条肽；退回 fallback 时报告里会写明 |

## 100 ns 的时间与体积预算（估算，实测为准）

| 项 | 估算 |
| --- | --- |
| 体系 | 6 nm 盒、1711 珠子（1664 W + 20 NA + 20 CL + 7 BB） |
| 步数 | 5,000,000 步 × 0.02 ps |
| 速度 | CG 小体系在 A4000 上量级 1,000–3,000 ns/day（**待实测**，全原子 617 是参照） |
| 墙钟 | 约 1–2.5 h，即 2–3 格 |
| 轨迹 | `nstxout-compressed = 5000`（每 100 ps 一帧）→ 1000 帧 × 1711 珠子 ≈ 7 MB，留在台式机 |

## 失败怎么读

`stages` 里哪一步 rc≠0 就看那一步的 `error_tail`：

| 症状 | 多半是 |
| --- | --- |
| `grompp` 说找不到 `W` / `[ moleculetype ]` | 力场文件不对（`...ff_molecules` 里没有 W/NA/CL）→ 重发第 2 单 |
| `grompp` 说 `#include` 找不到 | 力场目录没进 `GMXLIB`（`run` 已自动设；仍失败就把 `martini_dir` 显式传进来） |
| `mdrun` 立刻 LINCS / 压力爆炸 | 初始重叠：`box_nm` 加 0.5–1.0 重建再跑 |
| `pip` 全红、下载也失败 | 台式机没出网（它在轮询 git，一般不会）→ 用 `martini_dir` 指向已有力场 |
| 回执 `timeout` | 正常：那就是一格用完了，直接发第 4 单续跑 |
