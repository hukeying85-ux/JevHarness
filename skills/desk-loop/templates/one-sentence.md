# 一句话安装 / 新会话入口

把下面**一整行**发给任意新会话即可（不需要打开 arena.ai、不需要贴命令给本机）：

```text
安装 arena/03860148-jevharness 的 skills/cgmd-desktop + skills/desk-loop，与台式机打通，跑动力学到成功
```

助手看到这句应当立刻：

1. `git clone -b arena/03860148-jevharness https://github.com/hukeying85-ux/JevHarness.git /home/user/JevHarness`
2. `python3 skills/desk-loop/deskloop.py doctor`（分支守卫 + 台式机能力卡，约 60 s）
3. `python3 skills/desk-loop/deskloop.py handoff`（打印连接卡片）
4. 有任务就 `deskloop.py loop ...`，最后 `deskloop.py sync`；**不要**新建任何 `.ps1`/计划任务。

台式机侧一个字都不用敲：`CGMD-Hub-Poll` 本来就在每 60 s 取件执行。
