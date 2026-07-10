const STORAGE_KEY = 'tradingagents.web.uiLanguage';

export function createI18n({ catalog, languageField }) {
  let activeLocale = 'en';

  function initialize() {
    const selected = savedLanguage();
    languageField.value = selected;
    activeLocale = resolveLocale(selected);
    applyStaticTranslations();
  }

  function setLanguage(value) {
    try {
      window.localStorage.setItem(STORAGE_KEY, value);
    } catch {
      // Language persistence is optional.
    }
    activeLocale = resolveLocale(value);
    applyStaticTranslations();
  }

  function t(key) {
    return catalog[activeLocale]?.[key] ?? catalog.en[key] ?? key;
  }

  function locale() {
    return activeLocale;
  }

  function savedLanguage() {
    try {
      return window.localStorage.getItem(STORAGE_KEY) || 'auto';
    } catch {
      return 'auto';
    }
  }

  function resolveLocale(value) {
    if (value === 'zh' || value === 'en') return value;
    return navigator.language?.toLowerCase().startsWith('zh') ? 'zh' : 'en';
  }

  function applyStaticTranslations() {
    document.documentElement.lang = activeLocale === 'zh' ? 'zh-CN' : 'en';
    document.title = t('pageTitle');
    document.querySelectorAll('[data-i18n]').forEach(element => { element.textContent = t(element.dataset.i18n); });
    document.querySelectorAll('[data-i18n-title]').forEach(element => { element.title = t(element.dataset.i18nTitle); });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => { element.placeholder = t(element.dataset.i18nPlaceholder); });
  }

  return { initialize, setLanguage, t, locale };
}
