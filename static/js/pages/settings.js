import { api } from '../api.js';

const RULER_KEY = 'volume_ruler_source';
const RULER_OPTIONS = [
  { value: 'snapshot_file', label: '物化不可变快照（快照文件锁死只读，拒再改）' },
  { value: 'ledger_voucher', label: '旁路账册凭证（计划凭证表记挂载指纹与总字节）' },
];

export async function renderSettings(view, setMsg) {
  const j = await api('/api/settings');
  view.innerHTML = `
    <section class="card">
      <h2>台参数</h2>
      <p class="muted">体积标尺来源单选，两套落点互斥不同开；切换后已发布计划须同源才能合并/对账。</p>
      <div class="wall">
        ${(j.items || []).map(s => {
          if (s.key === RULER_KEY) {
            return `<article class="card">
              <h3>${s.label}</h3>
              <p class="muted">${s.key} · 单选，选定后发布按这套标尺单次落盘</p>
              <select data-key="${s.key}">
                ${RULER_OPTIONS.map(o => `<option value="${o.value}" ${o.value===s.value?'selected':''}>${o.label}</option>`).join('')}
              </select>
              <button data-save="${s.key}" class="primary" type="button" style="margin-top:.5rem">保存标尺来源</button>
            </article>`;
          }
          return `<article class="card">
            <h3>${s.label}</h3>
            <p class="muted">${s.key}</p>
            <input data-key="${s.key}" value="${s.value}" />
            <button data-save="${s.key}" class="primary" type="button" style="margin-top:.5rem">保存</button>
          </article>`;
        }).join('')}
      </div>
    </section>`;
  view.querySelectorAll('[data-save]').forEach(btn => {
    btn.onclick = async () => {
      try {
        const key = btn.dataset.save;
        const input = view.querySelector('[data-key="'+key+'"]');
        await api('/api/settings', { method:'POST', body: JSON.stringify({ key, value: input.value }) });
        setMsg(key === RULER_KEY ? '体积标尺来源已切换（两套落点互斥，只开一套）' : '已保存 ' + key);
        await renderSettings(view, setMsg);
      } catch (e) { setMsg(e.message, true); }
    };
  });
}
