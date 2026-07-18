const EVENT_TYPES = [
  'run_started', 'market_data_status', 'longitudinal_context_status',
  'architecture_evaluation_status',
  'message', 'tool_call', 'agent_status', 'report_section',
  'stats', 'run_completed', 'run_cancelled', 'error',
];

export function createEventStream({ onEvent, onReconnect }) {
  let source = null;

  function connect(runId) {
    close();
    source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    let reconnectReported = false;
    EVENT_TYPES.forEach(type => {
      source.addEventListener(type, event => {
        try {
          onEvent(type, JSON.parse(event.data));
        } catch (error) {
          console.error('Invalid runtime event', error);
        }
      });
    });
    source.onerror = () => {
      if (reconnectReported) return;
      reconnectReported = true;
      onReconnect();
    };
  }

  function close() {
    source?.close();
    source = null;
  }

  return { connect, close };
}
