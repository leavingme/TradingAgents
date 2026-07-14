export function createRunHistory({ api, element, locale, formatStatus, formatEventCount, onSelect, onDeleted }) {
  async function refresh() {
    let runs;
    try {
      runs = await api.listRuns();
    } catch {
      return;
    }
    element.replaceChildren(...runs.slice(0, 20).map(renderItem));
  }

  function renderItem(run) {
    const item = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = `${run.ticker}  ·  ${run.analysis_date}`;
    button.addEventListener('click', () => onSelect(run.run_id));

    const meta = document.createElement('div');
    meta.className = 'history-meta';
    const status = document.createElement('span');
    const displayStatus = run.status === 'completed' && run.data_status === 'degraded'
      ? 'data_degraded'
      : run.status === 'completed' && run.data_status === 'unavailable'
        ? 'data_unavailable'
        : run.status;
    status.className = `history-status ${displayStatus}`;
    status.textContent = formatStatus(displayStatus);
    const count = document.createElement('span');
    count.className = 'history-event-count';
    count.textContent = formatEventCount(run.event_count);
    meta.append(status, count, deleteButton(run));
    item.append(button, meta);
    return item;
  }

  function deleteButton(run) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn-icon delete-run-btn';
    button.title = locale() === 'zh' ? '删除运行记录' : 'Delete run';
    button.innerHTML = `
      <svg viewBox="0 0 16 16" fill="currentColor" width="12" height="12">
        <path d="M11 1.5v1h3.5a.5.5 0 0 1 0 1h-.538l-.853 10.66A2 2 0 0 1 11.115 16h-6.23a2 2 0 0 1-1.994-1.84L2.038 3.5H1.5a.5.5 0 0 1 0-1H5v-1A1.5 1.5 0 0 1 6.5 0h3A1.5 1.5 0 0 1 11 1.5Zm-5 0v1h4v-1a.5.5 0 0 0-.5-.5h-3a.5.5 0 0 0-.5.5ZM4.5 5.029l.5 8.5a.5.5 0 1 0 .998-.06l-.5-8.5a.5.5 0 1 0-.998.06Zm6.53-.06a.5.5 0 0 0-.51.49l-.5 8.5a.5.5 0 1 0 .998.06l.5-8.5a.5.5 0 0 0-.488-.55ZM1.962 3.5l.847 10.59a1 1 0 0 0 .997.91h6.23a1 1 0 0 0 .997-.91L11.892 3.5H1.962Z"/>
      </svg>`;
    button.addEventListener('click', async event => {
      event.stopPropagation();
      const message = locale() === 'zh' ? '您确定要删除此条运行记录吗？' : 'Are you sure you want to delete this run?';
      if (!confirm(message)) return;
      try {
        await api.deleteRun(run.run_id);
      } catch {
        return;
      }
      onDeleted(run.run_id);
      await refresh();
    });
    return button;
  }

  return { refresh };
}
