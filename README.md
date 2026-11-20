# 湖表压实台（cc-compact-lab）

CC_Codex 二期数据工程产品线：Tornado + 原生 JS 时间轴 SPA + SQLite。

## 主链

1. 小文件清单：登记湖区碎文件与体积
2. 压实计划：把碎文件编入计划
3. 重写合并：执行合并任务并回写状态
4. 体积对账：计划前后体积对照报告
5. 台参数：现行压实阈值与阈值说明

默认账号 `admin` / `123456`，端口 `7300`。

## 预留切口（出题用，基线先通）

- 计划与清单体积同源
- 合并失败半态 / 重跑
- 对账快照与现行体积

## 冻结体积标尺（压实计划发布）

碎文件编入计划后，发布时按台参数 `volume_ruler_source` 选定的**唯一一套**标尺单次落盘，
记录挂载目录（`lake/<目标表>`，与计划同源派生）、挂载总字节、挂载指纹（SHA256）与文件数。
两套落点互斥、不同开：

- `snapshot_file` 物化不可变快照：写 `instance/ruler_snapshots/plan_<id>.ruler.json`
  后置 `0444` 只读锁死，拒再改；
- `ledger_voucher` 旁路账册凭证（默认）：写 `volume_ruler_vouchers` 计划凭证表，
  `plan_id` 唯一，重复写入即拒。

发布经 `flock` 排他锁 + 库级唯一约束双保险，防两侧仓管同点发布双写覆盖。
重写合并与体积对账均从选定标尺读冻结总字节：缺标尺、跨源、挂载目录/指纹漂移一律中文拦截，
不落半态；对账页以标尺冻结总字节为同源 `before_bytes`，与合并字节对齐才亮「对账对齐」。

## 本地

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```
