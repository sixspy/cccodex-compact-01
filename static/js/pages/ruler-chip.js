// 体积标尺来源芯片：四屏联看，同源展示
const SOURCE_CLASS = {
  snapshot_file: 'snap',
  ledger_voucher: 'ledger',
};

export function sourceChip(ruler, { dim = false } = {}) {
  if (!ruler || !ruler.ruler_source) {
    return '<span class="chip draft">标尺未冻结 · 草稿计划</span>';
  }
  const cls = SOURCE_CLASS[ruler.ruler_source] || '';
  const same = ruler.same_source === false
    ? '<span class="chip off">与当前台参数不同源</span>'
    : '<span class="chip ok">与当前台参数同源</span>';
  return `<span class="chip ${cls}">标尺来源：${ruler.ruler_source_label}</span>`
    + (dim ? '' : same);
}

export function rulerDetail(ruler) {
  if (!ruler || !ruler.ruler_source) {
    return '<div class="kv muted"><span>发布后此处显示冻结挂载目录、总字节与挂载指纹</span></div>';
  }
  return `
    <div class="kv">
      <span>挂载目录：<code>${ruler.mount_dir || '—'}</code></span>
      <span>冻结总字节：<strong>${ruler.total_bytes ?? 0}</strong> 字节 · 文件 ${ruler.file_count ?? 0}</span>
      <span>挂载指纹：<code>${ruler.mount_fingerprint || '—'}</code></span>
    </div>`;
}
