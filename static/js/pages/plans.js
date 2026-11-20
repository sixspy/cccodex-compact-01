import { api } from '../api.js';
import { sourceChip, rulerDetail } from './ruler-chip.js';

export async function renderPlans(view, setMsg) {
  const j = await api('/api/plans');
  view.innerHTML = `
    <section class="card">
      <h2>压实计划</h2>
      <p class="muted">发布即按台参数选定的体积标尺单次落盘；两套落点互斥，只亮一条标尺来源。</p>
      <div class="row">
        <label>编号<input id="code" value="CP-NEW-1" /></label>
        <label>标题<input id="title" value="新压实计划" /></label>
        <label>目标表<input id="table" value="dw_payments" /></label>
        <button class="primary" id="create" type="button">创建计划</button>
      </div>
    </section>
    <section class="wall" style="margin-top:1rem">
      ${(j.items || []).map(p => `<article class="card">
        <h3>${p.plan_code}</h3>
        <span class="tag">${p.status}</span>
        <div style="margin:.5rem 0">${sourceChip(p.ruler)}</div>
        <p>${p.title}</p>
        <p class="muted">${p.target_table} · ${p.item_count} 文件 · 现行挂载 ${p.plan_bytes} 字节</p>
        ${rulerDetail(p.ruler)}
        <div class="row" style="margin-top:.6rem">
          <button data-attach="${p.id}" type="button">挂入碎文件</button>
          <button data-pub="${p.id}" class="primary" type="button">点亮发布</button>
          <button data-detail="${p.id}" type="button">详情</button>
        </div>
        <pre class="muted" id="d${p.id}"></pre>
      </article>`).join('') || '<p class="muted">暂无计划</p>'}
    </section>`;
  document.getElementById('create').onclick = async () => {
    try {
      await api('/api/plans', { method:'POST', body: JSON.stringify({
        plan_code: document.getElementById('code').value,
        title: document.getElementById('title').value,
        target_table: document.getElementById('table').value,
      })});
      setMsg('计划已创建（草稿，尚未冻结体积标尺）');
      await renderPlans(view, setMsg);
    } catch (e) { setMsg(e.message, true); }
  };
  view.querySelectorAll('[data-attach]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/plans/' + btn.dataset.attach + '/attach', { method:'POST', body:'{}' });
        setMsg('挂入 ' + r.attached + ' 个碎文件；已发布计划的挂载变动会在合并/对账时被同源闸门拦截');
        await renderPlans(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-pub]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/plans/' + btn.dataset.pub + '/publish', { method:'POST', body:'{}' });
        const ru = r.item.ruler || {};
        setMsg('已发布：标尺来源「' + ru.ruler_source_label + '」，冻结总字节 ' + ru.total_bytes + '（单次落盘，拒再改）');
        await renderPlans(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
  view.querySelectorAll('[data-detail]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const r = await api('/api/plans/' + btn.dataset.detail);
        document.getElementById('d' + btn.dataset.detail).textContent = JSON.stringify(
          { plan: r.plan, ruler: r.ruler, items: r.items }, null, 2
        );
      } catch (e) { setMsg(e.message, true); }
    };
  });
}
