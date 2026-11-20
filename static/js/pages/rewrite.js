import { api } from '../api.js';

export async function renderRewrite(view, setMsg) {
  const plans = await api('/api/plans');
  const jobs = await api('/api/rewrite/jobs');
  const options = (plans.items || []).map(p => {
    const ru = p.ruler || {};
    const tag = ru.ruler_source ? ru.ruler_source_label : '标尺未冻结';
    return `<option value="${p.id}">${p.plan_code} · ${p.status} · ${tag}</option>`;
  }).join('');
  view.innerHTML = `
    <section class="card">
      <h2>重写合并</h2>
      <p class="muted">合并落库前校验同源标尺：挂载目录/指纹/总字节拧了就中文拦截，不落半态。</p>
      <div class="row">
        <label>计划<select id="pid">${options}</select></label>
        <button class="primary" id="go" type="button">启动合并</button>
      </div>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(jobs.items || []).map(j => `<article class="card">
        <h3>${j.plan_code || ('计划#'+j.plan_id)}</h3>
        <span class="tag">${j.status}</span>
        <span class="chip ${j.ruler_source==='snapshot_file'?'snap':'ledger'}">标尺：${j.ruler_source==='snapshot_file'?'物化不可变快照':(j.ruler_source==='ledger_voucher'?'旁路账册凭证':j.ruler_source||'未知')}</span>
        <p class="muted">${j.message}</p>
        <p>合并字节 ${j.merged_bytes} · 标尺冻结 ${j.ruler_bytes || 0}</p>
      </article>`).join('') || '<p class="muted">尚无合并任务</p>'}
    </section>`;
  document.getElementById('go').onclick = async () => {
    try {
      const pid = document.getElementById('pid').value;
      const r = await api('/api/rewrite/plans/' + pid + '/start', { method:'POST', body:'{}' });
      setMsg('合并完成 · ' + r.job.status + ' · 同源标尺字节 ' + r.job.ruler_bytes);
      await renderRewrite(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
}
