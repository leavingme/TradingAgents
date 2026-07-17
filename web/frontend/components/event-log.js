export function createEventLog({ element, t, locale, formatAgentName, formatStatus, formatStats }) {
  function append(type, agent, text) {
    const item = document.createElement('article');
    item.className = 'event';
    const head = document.createElement('div');
    head.className = 'event-head';
    const badge = document.createElement('span');
    badge.className = `event-type event-type-${type}`;
    badge.textContent = formatType(type);
    const agentLabel = document.createElement('span');
    agentLabel.className = 'event-agent';
    agentLabel.textContent = agent ? formatAgentName(agent, locale()) : t('system');
    const time = document.createElement('span');
    time.className = 'event-time';
    time.textContent = new Date().toLocaleTimeString();
    const body = document.createElement('div');
    body.className = 'event-text';
    body.textContent = text || '';
    head.append(badge, agentLabel, time);
    item.append(head, body);
    element.append(item);
    element.scrollTop = element.scrollHeight;
  }

  function text(type, content) {
    if (!content) return '';
    if (typeof content === 'string') return content;
    if (type === 'message') return content.text || '';
    if (type === 'tool_call') return `${content.name || 'tool'}  ${JSON.stringify(content.args || {})}`;
    if (type === 'vendor_attempt') {
      const outcome = content.selected ? `${content.status} · selected` : content.status;
      const reason = content.error_detail ? ` · ${content.error_detail}` : '';
      return `${content.category || 'data'} · ${content.method || 'call'} · #${content.attempt} ${content.vendor} · ${outcome}${reason} · call ${content.call_id}`;
    }
    if (type === 'report_section') return `${content.section || 'report'} ${t('reportUpdated')}`;
    if (type === 'agent_status') return formatStatus(content.status || '');
    if (type === 'run_started') return `${content.ticker} · ${content.analysis_date}`;
    if (type === 'market_data_status') {
      return `${content.status || ''} · ${content.market_data_date || content.requested_analysis_date || ''}`;
    }
    if (type === 'longitudinal_context_status') {
      return `${content.status || ''} · same ${content.same_symbol_included_count || 0}/${content.same_symbol_scanned_count || 0} · cross ${content.cross_symbol_included_count || 0}/${content.cross_symbol_scanned_count || 0}`;
    }
    if (type === 'stats') return formatStats(content);
    return JSON.stringify(content);
  }

  function clear() {
    element.replaceChildren();
  }

  function formatType(type) {
    const key = {
      run_started: 'eventRunStarted', message: 'eventMessage', tool_call: 'eventToolCall',
      market_data_status: 'eventMarketDataStatus',
      longitudinal_context_status: 'eventLongitudinalContextStatus',
      vendor_attempt: 'eventVendorAttempt',
      agent_status: 'eventAgentStatus', report_section: 'eventReportSection', stats: 'eventStats',
      run_completed: 'eventRunCompleted', run_cancelled: 'eventRunCancelled', error: 'eventError',
    }[type];
    return key ? t(key) : type.replace(/_/g, ' ');
  }

  return { append, text, clear };
}
