export function createRouter({ elements, getCurrentRunId, onSelectRun }) {
  const { runControls, runView, settingsView, providersView, runButton, settingsButton, providersButton } = elements;

  function show(view, updateHash = true) {
    const settingsActive = view === 'settings';
    const providersActive = view === 'providers';
    const runActive = view === 'run';
    runControls.classList.toggle('hidden', !runActive);
    runView.classList.toggle('hidden', !runActive);
    settingsView.classList.toggle('hidden', !settingsActive);
    providersView.classList.toggle('hidden', !providersActive);
    runControls.hidden = !runActive;
    runView.hidden = !runActive;
    settingsView.hidden = !settingsActive;
    providersView.hidden = !providersActive;
    runButton.classList.toggle('active', runActive);
    settingsButton.classList.toggle('active', settingsActive);
    providersButton.classList.toggle('active', providersActive);
    if (!updateHash) return;
    if (settingsActive || providersActive) {
      window.location.hash = view;
    } else if (getCurrentRunId()) {
      setRun(getCurrentRunId());
    } else {
      window.history.replaceState(null, '', window.location.pathname);
    }
  }

  function handleHash() {
    const hash = window.location.hash.slice(1);
    if (hash === 'settings' || hash === 'providers') {
      show(hash, false);
      resetScroll();
      return;
    }
    if (hash.startsWith('run=')) {
      const runId = decodeURIComponent(hash.slice(4));
      show('run', false);
      if (runId && runId !== getCurrentRunId()) onSelectRun(runId);
      resetScroll();
      return;
    }
    show('run', false);
    resetScroll();
  }

  function setRun(runId, replace = false) {
    const target = `#run=${encodeURIComponent(runId)}`;
    if (window.location.hash === target) return;
    if (replace) window.history.replaceState(null, '', target);
    else window.location.hash = target;
  }

  window.addEventListener('hashchange', handleHash);
  return { show, handleHash, setRun };
}

function resetScroll() {
  window.scrollTo(0, 0);
  window.requestAnimationFrame(() => window.scrollTo(0, 0));
}
