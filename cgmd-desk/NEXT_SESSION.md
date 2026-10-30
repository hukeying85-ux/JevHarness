# 把 100 ns 粗粒化跑起来：给「0fuye 仓库会话」的一段话

本会话的 Arena token 只覆盖 `hukeying85-ux/JevHarness`（对 0fuye 读得到、写 403，证据在 `README.md`），
所以最后一步必须由**一个会话在 0fuye 仓库里**完成。那种会话的 token 就在 0fuye 上。

在 Arena 里新开一个对话、把这个仓库选成 `hukeying85-ux/0fuye`（分支 `arena/32cd826e-0fuye`），
然后把下面整段粘进去。它会长驱直入，不需要再解释任何背景：

```text
你是 CGMD 项目执行代理，会话在 hukeying85-ux/0fuye（分支 arena/32cd826e-0fuye）。
台式机 DESKTOP-IEUDGS5 的基座已经在跑（CGMD-Hub-Poll 60 s 轮询），不要重装、不要新建任何轮询脚本。

任务：把「粗粒化 100 ns」打通并跑完，全程你自己动手，不要让我粘命令。

第 0 步 落地一个已经写好并测过的补丁（由 JevHarness 会话交接）：
  git clone --depth 1 -b arena/80c9d20f-jevharness https://github.com/hukeying85-ux/JevHarness.git /tmp/jh
  cp /tmp/jh/cgmd-desk/0fuye-cgmd-kind.patch /tmp/cgmd-kind.patch
  git checkout -b arena/cgmd-kind && git am /tmp/cgmd-kind.patch
  python3 -m pytest tests/ -q          # 期望 202 passed, 5 skipped
  git push -u origin arena/cgmd-kind
  gh pr create --base arena/32cd826e-0fuye --head arena/cgmd-kind --fill
  gh pr merge <PR#> --merge            # 值守每 60 s reset --hard，下一轮就带新代码

第 1-4 步 按 /tmp/jh/cgmd-desk/jobs.md 依次发四单：cgmd probe → cgmd ff → cgmd all(ns=100, 第一格 1 h) → cgmd run(resume=true) 循环到 finished。

硬规则：轨迹类文件（.xtc/.trr/.tpr/.gro/.edr/.cpt）一律不进 git；不改 0fuye 的 main；不碰 allow_shell。

汇报格式：主机 / 值守心跳 / GPU / GROMACS / 各单工单号与耗时 / CG 体系的序列与珠子数 /
ns/day / 100 ns 是否 finished / 自检 pass-warn-fail；没实测的字段写「未验证」，不要编。
```

## 或者（更省事的一条）

如果你不想开新对话：把这台 Arena 的 GitHub 授权里**加上 `hukeying85-ux/0fuye` 这个仓库**
（GitHub → Settings → Applications → Arena → Configure → Repository access），
然后回来跟我说一句「加好了」，我这边立刻重推同一份补丁并连发四单，一直到 100 ns 跑完给你报表。

## 两种方式之后都会发生什么

1. 合并后 60 s 内，值守 `git reset --hard` 带上 `cgmd` 这个任务类型；
2. `probe` 告诉我们在哪台解释器上装力场；
3. `ff` 把 Martini 3 力场拉到 `%USERPROFILE%\cgmd-runs\martini3`（不入库）；
4. `all` 从 `F:\0wsh\asd` 一带找到你最近跑的那条肽（从 `.gro` 残基名还原序列），建 6 nm 盒、
   EM → 200 ps NPT → 生产第一格；
5. `run(resume=true)` 一格一格续到 `Finished mdrun`，100 ns 齐活，回执里给出 ns/day、Rg、接触簇。
