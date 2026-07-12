const STORAGE_KEY = 'tradingagents.web.settings';

export function createSettingsController({ form, fields, modelPresets, onProviderChange, onSave }) {
  let saveTimer = null;
  const {
    llmProvider, quickThinkLlm, deepThinkLlm, backendUrl, outputLanguage,
    customOutputLanguage, researchDepth, googleThinkingLevel,
    openaiReasoningEffort, anthropicEffort,
  } = fields;

  form.addEventListener('input', save);
  form.addEventListener('change', save);
  outputLanguage.addEventListener('change', updateOutputLanguageMode);
  llmProvider.addEventListener('change', () => {
    const preset = modelPresets[llmProvider.value];
    if (preset) {
      quickThinkLlm.value = preset.quick;
      deepThinkLlm.value = preset.deep;
    }
    updateProviderOptions();
    onProviderChange();
    save();
  });

  function applyDefaults(defaults) {
    setValue(llmProvider, defaults.llm_provider);
    setValue(quickThinkLlm, defaults.quick_think_llm);
    setValue(deepThinkLlm, defaults.deep_think_llm);
    setValue(backendUrl, defaults.backend_url);
    setValue(researchDepth, defaults.research_depth);
    setValue(googleThinkingLevel, defaults.google_thinking_level);
    setValue(openaiReasoningEffort, defaults.openai_reasoning_effort);
    setValue(anthropicEffort, defaults.anthropic_effort);
    setOutputLanguage(defaults.output_language);
    updateProviderOptions();
  }

  function applySaved(serverSettings, allowLegacyMigration = false) {
    let saved = serverSettings;
    if ((!saved || !Object.keys(saved).length) && allowLegacyMigration) {
      try {
        saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
      } catch {
        saved = null;
      }
    }
    if (!saved) return;
    setValue(llmProvider, saved.llm_provider);
    setValue(quickThinkLlm, saved.quick_think_llm);
    setValue(deepThinkLlm, saved.deep_think_llm);
    setValue(backendUrl, saved.backend_url);
    setValue(researchDepth, saved.research_depth);
    setValue(googleThinkingLevel, saved.google_thinking_level);
    setValue(openaiReasoningEffort, saved.openai_reasoning_effort);
    setValue(anthropicEffort, saved.anthropic_effort);
    setOutputLanguage(saved.output_language);
    updateProviderOptions();
    if (allowLegacyMigration) {
      try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* optional */ }
    }
  }

  function current() {
    const depth = Number(researchDepth.value);
    return {
      research_depth: Number.isFinite(depth) && depth > 0 ? depth : null,
      llm_provider: llmProvider.value,
      quick_think_llm: quickThinkLlm.value.trim() || null,
      deep_think_llm: deepThinkLlm.value.trim() || null,
      backend_url: backendUrl.value.trim() || null,
      output_language: selectedOutputLanguage(),
      google_thinking_level: googleThinkingLevel.value || null,
      openai_reasoning_effort: openaiReasoningEffort.value || null,
      anthropic_effort: anthropicEffort.value || null,
    };
  }

  function save() {
    const value = current();
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => onSave?.(value), 250);
  }

  function reset(defaults) {
    if (defaults) {
      applyDefaults(defaults);
      save();
    }
  }

  function selectedOutputLanguage() {
    return outputLanguage.value === '__custom'
      ? customOutputLanguage.value.trim() || 'Chinese'
      : outputLanguage.value;
  }

  function setOutputLanguage(value) {
    if (!value) return;
    const known = Array.from(outputLanguage.options).some(option => option.value === value);
    outputLanguage.value = known ? value : '__custom';
    customOutputLanguage.value = known ? '' : value;
    updateOutputLanguageMode();
  }

  function updateOutputLanguageMode() {
    const custom = outputLanguage.value === '__custom';
    customOutputLanguage.hidden = !custom;
    customOutputLanguage.required = custom;
  }

  function updateProviderOptions() {
    document.querySelectorAll('.provider-option').forEach(element => { element.hidden = true; });
    const selector = { google: '.provider-google', openai: '.provider-openai', anthropic: '.provider-anthropic' }[llmProvider.value];
    if (selector) document.querySelectorAll(selector).forEach(element => { element.hidden = false; });
  }

  return { applyDefaults, applySaved, current, save, reset };
}

function setValue(field, value) {
  if (field && value !== undefined && value !== null && value !== '') field.value = String(value);
}
