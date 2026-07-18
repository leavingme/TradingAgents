export function createEventLog({ element, t, locale, formatAgentName, formatStatus, formatStats }) {
  function compactNumber(value) {
    const number = Number(value) || 0;
    if (number >= 1000000) return `${(number / 1000000).toFixed(1)}M`;
    if (number >= 1000) return `${(number / 1000).toFixed(1)}K`;
    return String(number);
  }

  function evaluationCode(value) {
    const key = {
      insufficient_outcome_samples: 'evaluationCodeInsufficientOutcomeSamples',
      outcome_uncertainty_not_ready: 'evaluationCodeOutcomeUncertaintyNotReady',
      incomplete_input_audit: 'evaluationCodeIncompleteInputAudit',
      ready_for_controlled_experiment_design: 'evaluationCodeReadyForExperiment',
      continue_sample_collection: 'evaluationCodeContinueCollection',
      repair_temporal_evidence: 'evaluationCodeRepairTemporalEvidence',
      repair_input_audit: 'evaluationCodeRepairInputAudit',
      investigate_persistent_underperformance: 'evaluationCodeInvestigatePersistent',
      investigate_recent_deterioration: 'evaluationCodeInvestigateRecent',
      design_controlled_challenger: 'evaluationCodeDesignChallenger',
    }[value];
    return key ? t(key) : String(value || '').replaceAll('_', ' ');
  }

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
    if (type === 'architecture_evaluation_status') {
      const architecture = content.current_architecture || {};
      const tools = Array.isArray(content.context_cost_diagnostic?.top_tools)
        ? content.context_cost_diagnostic.top_tools.slice(0, 3)
        : [];
      const hotspots = tools.length
        ? ` · ${t('toolOutputHotspots')}: ${tools.map(row => `${row.tool} ${compactNumber(row.output_chars)}`).join(', ')}`
        : '';
      return `${content.status || ''} · ${architecture.sample_count || 0} ${t('samples')} · ${evaluationCode(architecture.readiness_status || 'insufficient_outcome_samples')} · ${evaluationCode(architecture.recommended_action || 'continue_sample_collection')}${hotspots}`;
    }
    if (type === 'stats') {
      const tools = content.by_tool && typeof content.by_tool === 'object'
        ? Object.entries(content.by_tool)
          .filter(([, values]) => values && Number.isInteger(values.output_chars) && values.output_chars >= 0)
          .sort(([leftName, left], [rightName, right]) => (
            right.output_chars - left.output_chars || leftName.localeCompare(rightName)
          ))
          .slice(0, 3)
        : [];
      const hotspots = tools.length
        ? ` · ${t('toolOutputHotspots')}: ${tools.map(([tool, values]) => `${tool} ${compactNumber(values.output_chars)}`).join(', ')}`
        : '';
      return `${formatStats(content)}${hotspots}`;
    }
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
      architecture_evaluation_status: 'eventArchitectureEvaluationStatus',
      vendor_attempt: 'eventVendorAttempt',
      agent_status: 'eventAgentStatus', report_section: 'eventReportSection', stats: 'eventStats',
      run_completed: 'eventRunCompleted', run_cancelled: 'eventRunCancelled', error: 'eventError',
    }[type];
    return key ? t(key) : type.replace(/_/g, ' ');
  }

  return { append, text, clear };
}
