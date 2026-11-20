import { api } from '../api.js';
import { sourceChip } from './ruler-chip.js';

export async function renderReconcile(view, setMsg) {
  const plans = await api('/api/plans');
  const reports = await api('/api/reconcile/reports');
  const options = (plans.items || []).map(p =>
    `<option value="${p.id}">${p.plan_code}（${p.ruler && p.ruler.ruler_source ? p.ruler.ruler_source_label : '标尺未冻结'}）</option>`
  ).join('');
  view.innerHTML = `
    <section class="card">
      <h2>体积对账</h2>
      <p class="muted">对账总字节只采用发布时冻结的同源标尺，不跟现行目录猜数；跨源或缺标尺会被中文拦截。</p>
      <div class="row">
        <label>计划<select id="pid">${options}</select></label>
        <button class="primary" id="go" type="button">跑对账</button>
      </div>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(reports.items || []).map(r => `<article class="card">
        <h3>${r.plan_code || ('计划#'+r.plan_id)}</h3>
        <span class="chip ${r.ruler_source==='snapshot_file'?'snap':'ledger'}">标尺来源：${r.ruler_source==='snapshot_file'?'物化不可变快照':(r.ruler_source==='ledger_voucher'?'旁路账册凭证':r.ruler_source||'未知')}</span>
        ${r.aligned ? '<span class="chip ok">对账对齐</span>' : '<span class="chip off">未对齐/待合并</span>'}
        <p>${r.summary}</p>
        <div class="kv muted">
          <span>挂载目录：<code>${r.mount_dir || '—'}</code></span>
          <span>同源总字节：<strong>${r.before_bytes}</strong> · 合并后 ${r.after_bytes} · 文件 ${r.file_count}</span>
          <span>挂载指纹：<code>${r.mount_fingerprint || '—'}</code></span>
        </div>
      </article>`).join('') || '<p class="muted">暂无对账报告</p>'}
    </section>`;
  document.getElementById('go').onclick = async () => {
    try {
      const r = await api('/api/reconcile/reports', {
        method:'POST',
        body: JSON.stringify({ plan_id: Number(document.getElementById('pid').value) }),
      });
      setMsg(r.report.summary);
      await renderReconcile(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
}
