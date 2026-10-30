# `cgmd` 落地后要发的三单（照抄即可，不需要人动手）

前置：`cgmd` kind 已合进 `arena/32cd826e-0fuye`（见 `README.md`）。客户端仍然是只读的 0fuye 克隆 +
本仓（JevHarness）自己的 `hub/mailbox`：

```bash
git clone -b arena/32cd826e-0fuye https://github.com/hukeying85-ux/0fuye.git /tmp/0fuye
```

## 第 1 单 · 环境清点（5 s）

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "probe", "roots": ["F:\\0wsh\\asd", "F:\\0wsh", "F:\\"]}' \
  --read-repo /tmp/0fuye --timeout 600
```

看 `detail.ops.detail`：`pythons[0].version`（≥3.8 才能装 vermouth）、`gmx.version`、`martini.file`。

## 第 2 单 · 拿 Martini 3 力场

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "ff", "python": "<第1单里挑中的解释器绝对路径>", "install_timeout": 900}' \
  --read-repo /tmp/0fuye --timeout 1200
```

先 `pip install martini-forcefields`；失败自动退回
`codeload.github.com/marrink-lab/martini-forcefields` 下载并解包到 `%USERPROFILE%\cgmd-runs\martini3`。
力场不入库（第三方许可），只落在台式机上。

## 第 3 单 · 找那条肽 + 建体系 + 跑 CG（默认 1 ns）

```bash
PYTHONPATH=/tmp/0fuye python3 -m core.hub_mailbox --repo . run --kind cgmd \
  --json-args '{"mode": "all", "roots": ["F:\\0wsh\\asd", "F:\\0wsh", "F:\\"],
                "days": 120, "depth": 4, "box_nm": 6.0, "ns": 1.0, "gpu_id": 0,
                "fallback_sequence": "KLVFFAE"}' \
  --read-repo /tmp/0fuye --timeout 2400
```

- `search` 会按 mtime 从新到旧列出候选目录，并从 `.gro` 的残基名**还原序列**；
  找不到就退回 `fallback_sequence`（`KLVFFAE` = Aβ16–22，正好是文档里点名的 Aβ 片段）。
- `build` 写下 `system.gro / peptide.itp / topol.top / em.mdp / eq.mdp / prod.mdp`
  （工作目录默认 `%USERPROFILE%\cgmd-runs\cg-<时间戳>`）。
- `run`：`grompp`(em/eq/prod) → `mdrun -nb gpu -gpu_id 0` ×3，报
  `report.performance_ns_per_day`、`report.structure.start/final.rg_nm`、`contact clusters`。

## 回执里要核对的字段

| 字段 | 期望 |
| --- | --- |
| `result.status` | `ok` |
| `result.detail.ops.detail.report.accelerator` | `gpu` |
| `...report.performance_ns_per_day` | > 0（CG 体系应显著高于全原子烟测的 617） |
| `...report.finished` | `true` |
| `...report.structure.final.peptide_beads` | == 残基数 |
| `...stages[]` 各 `returncode` | 全 0 |
| `...detail.system.sequence` | 从 F 盘还原的那条肽（或 fallback，报告里会写明来源） |

## 失败怎么读

`stages` 里哪一步 rc≠0 就看哪一步的 `error_tail`：

| 症状 | 多半是 |
| --- | --- |
| `grompp` 说找不到 `W` / `[ moleculetype ]` | 力场文件不对（`detail.ops.detail.ff_molecules` 里没有 W/NA/CL）→ 重发第 2 单 |
| `grompp` 说 `#include` 找不到文件 | 力场目录不在 `GMXLIB`（`run` 已自动设成力场目录；仍失败就把 `martini_dir` 显式传进来） |
| `mdrun` 立刻 LINCS/气压爆炸 | 初始重叠：把 `box_nm` 调大 0.5–1.0 再跑 |
| `pip` 全红、下载也失败 | 台式机没有出网（但它在轮询 git，一般不会）→ 改用 `martini_dir` 指向已有力场 |
