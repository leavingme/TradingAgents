const STORAGE_KEY = 'tradingagents.web.providers';
const LEGACY_CORE_DEFAULT = ['westock', 'longbridge_mcp', 'longbridge', 'alpha_vantage'];
const LEGACY_NEWS_DEFAULT = ['westock', 'duckduckgo', 'alpha_vantage'];
const LEGACY_TECHNICAL_DEFAULT = ['longbridge_mcp', 'longbridge', 'westock'];

const CATEGORY_VENDORS = {
  core_stock_apis: ['longbridge_mcp', 'longbridge', 'westock', 'alpha_vantage'],
  technical_indicators: ['longbridge_mcp', 'longbridge', 'westock', 'alpha_vantage'],
  fundamental_data: ['longbridge_mcp', 'longbridge', 'westock', 'alpha_vantage'],
  news_data: ['longbridge_mcp', 'longbridge', 'westock', 'duckduckgo', 'alpha_vantage'],
  social_data: ['bird', 'reddit'],
  macro_data: ['fred'],
  prediction_markets: ['polymarket'],
};

const PROVIDER_META = {
  westock: { name: 'Westock' },
  longbridge_mcp: { name: 'Longbridge MCP' },
  longbridge: { name: 'Longbridge CLI' },
  alpha_vantage: { name: 'Alpha Vantage' },
  duckduckgo: { name: 'DuckDuckGo' },
  fred: { name: 'FRED' },
  polymarket: { name: 'Polymarket' },
  bird: { name: 'Bird (X/Twitter)' },
  reddit: { name: 'Reddit', verifiable: false },
};

const FALLBACK_DEFAULTS = {
  core_stock_apis: 'longbridge_mcp, longbridge, westock',
  technical_indicators: 'westock, longbridge_mcp',
  fundamental_data: 'longbridge_mcp, longbridge, westock',
  news_data: 'longbridge_mcp, longbridge, westock, duckduckgo, alpha_vantage',
  social_data: 'bird, reddit',
  macro_data: 'fred',
  prediction_markets: 'polymarket',
};

export function createProviderManager({ api, t, locale, configDefaults, envStatus, setEnvStatus, ohlcvSettingsBody }) {
  let state = {};

  function save() {
    api.saveWebConfig({ providers: state }).catch(error => {
      console.error('Failed to persist provider settings', error);
    });
  }

  function parseDefaults(category, value) {
    const configured = String(value || '').split(',').map(item => item.trim()).filter(Boolean);
    const allowed = CATEGORY_VENDORS[category];
    return [
      ...configured.filter(id => allowed.includes(id)).map(id => ({ id, enabled: true })),
      ...allowed.filter(id => !configured.includes(id)).map(id => ({ id, enabled: false })),
    ];
  }

  function normalize(category, rows) {
    const allowed = CATEGORY_VENDORS[category];
    const normalized = [];
    const seen = new Set();
    (Array.isArray(rows) ? rows : []).forEach(row => {
      if (!allowed.includes(row?.id) || seen.has(row.id)) return;
      normalized.push({ id: row.id, enabled: row.enabled !== false });
      seen.add(row.id);
    });
    allowed.forEach(id => {
      if (!seen.has(id)) normalized.push({ id, enabled: false });
    });
    return normalized;
  }

  function load(serverProviders = null, allowLegacyMigration = false) {
    let saved = allowLegacyMigration ? null : serverProviders;
    if (allowLegacyMigration) {
      try {
        saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
      } catch {
        saved = null;
      }
    }
    if (Array.isArray(saved?.core_stock_apis)) {
      const savedIds = saved.core_stock_apis.map(row => row?.id);
      const isLegacyDefault = savedIds.length === LEGACY_CORE_DEFAULT.length
        && savedIds.every((id, index) => id === LEGACY_CORE_DEFAULT[index]);
      if (isLegacyDefault) {
        const byId = new Map(saved.core_stock_apis.map(row => [row.id, row]));
        saved.core_stock_apis = CATEGORY_VENDORS.core_stock_apis.map(id => byId.get(id));
      }
    }
    // Reddit was historically always fetched by Sentiment Analyst and had no
    // visible setting. Keep it enabled when migrating an older saved config.
    if (Array.isArray(saved?.social_data)
      && !saved.social_data.some(row => row?.id === 'reddit')) {
      saved.social_data.push({ id: 'reddit', enabled: true });
    }
    const defaults = configDefaults()?.data_vendors || FALLBACK_DEFAULTS;
    if (Array.isArray(saved?.news_data)) {
      const enabledNewsIds = saved.news_data
        .filter(row => row?.enabled !== false)
        .map(row => row?.id);
      const isLegacyNewsDefault = enabledNewsIds.length === LEGACY_NEWS_DEFAULT.length
        && enabledNewsIds.every((id, index) => id === LEGACY_NEWS_DEFAULT[index]);
      if (isLegacyNewsDefault) {
        saved.news_data = parseDefaults('news_data', defaults.news_data);
      }
    }
    if (Array.isArray(saved?.technical_indicators)) {
      const enabledTechnicalIds = saved.technical_indicators
        .filter(row => row?.enabled !== false)
        .map(row => row?.id);
      const isLegacyTechnicalDefault = enabledTechnicalIds.length === LEGACY_TECHNICAL_DEFAULT.length
        && enabledTechnicalIds.every((id, index) => id === LEGACY_TECHNICAL_DEFAULT[index]);
      if (isLegacyTechnicalDefault) {
        saved.technical_indicators = parseDefaults(
          'technical_indicators',
          defaults.technical_indicators,
        );
      }
    }
    state = {};
    Object.keys(CATEGORY_VENDORS).forEach(category => {
      state[category] = saved && typeof saved === 'object'
        ? normalize(category, saved[category])
        : parseDefaults(category, defaults[category]);
    });
    if (allowLegacyMigration) {
      try { window.localStorage.removeItem(STORAGE_KEY); } catch { /* optional */ }
      save();
    }
    refresh();
  }

  function reset() {
    load(null, false);
    save();
  }

  function refresh() {
    if (!Object.keys(state).length) return;
    Object.keys(CATEGORY_VENDORS).forEach(renderCategory);
    renderOhlcvTable();
  }

  function renderCategory(category) {
    const container = document.querySelector(`#list_${category}`);
    if (!container) return;
    const vendors = state[category] || [];
    const environment = envStatus();
    const rows = vendors.map((vendor, index) => providerRow({
      category,
      vendor,
      index,
      vendors,
      environment,
    }));
    container.replaceChildren(...rows);
    if (category === 'core_stock_apis') renderOhlcvTable();
  }

  function providerRow({ category, vendor, index, vendors, environment }) {
    const item = document.createElement('li');
    item.className = `provider-item${vendor.enabled ? '' : ' disabled'}`;
    item.dataset.vendor = vendor.id;
    item.dataset.index = String(index);

    const meta = PROVIDER_META[vendor.id] || { name: vendor.id };
    const verification = environment?.vendor_verifications?.[category]?.[vendor.id];
    const verificationState = verification?.status || 'unverified';
    const credential = credentialStatus(environment?.data_vendors?.[vendor.id]);
    item.innerHTML = `
      <div class="provider-item-left">
        <input type="checkbox" class="provider-enable-checkbox" ${vendor.enabled ? 'checked' : ''} />
        <span class="provider-identity">
          <span class="provider-name">${escapeHtml(meta.name)}</span>
          <span class="provider-verification-detail" title="${escapeHtml(verification?.detail || '')}">${escapeHtml(formatVerification(verification))}</span>
        </span>
      </div>
      <div class="provider-item-right">
        <span class="vendor-health-badge ${verificationState}">${escapeHtml(formatHealth(verificationState))}</span>
        <span class="env-status-badge ${credential.className}">${escapeHtml(credential.label)}</span>
        ${meta.verifiable === false ? '' : `<button type="button" class="btn-verify-vendor" title="${escapeHtml(t('vendorVerify'))}" aria-label="${escapeHtml(t('vendorVerify'))}">↻</button>`}
        <div class="provider-order-buttons">
          <button type="button" class="btn-order btn-order-up" title="Move Up" ${index === 0 ? 'disabled' : ''}>▲</button>
          <button type="button" class="btn-order btn-order-down" title="Move Down" ${index === vendors.length - 1 ? 'disabled' : ''}>▼</button>
        </div>
      </div>`;

    item.querySelector('.provider-enable-checkbox').addEventListener('change', event => {
      vendor.enabled = event.currentTarget.checked;
      item.classList.toggle('disabled', !vendor.enabled);
      save();
      renderOhlcvTable();
    });
    item.querySelector('.btn-verify-vendor')?.addEventListener('click', event => {
      verify(category, vendor.id, event.currentTarget);
    });
    item.querySelector('.btn-order-up').addEventListener('click', () => move(category, index, -1));
    item.querySelector('.btn-order-down').addEventListener('click', () => move(category, index, 1));
    return item;
  }

  function credentialStatus(status) {
    if (!status?.required) return { className: 'optional', label: t('apiKeyNotRequired') };
    return status.configured
      ? { className: 'configured', label: t('apiKeyConfigured') }
      : { className: 'missing', label: t('apiKeyMissing') };
  }

  async function verify(category, vendor, button) {
    button.disabled = true;
    button.classList.add('loading');
    button.title = t('vendorVerifying');
    try {
      const result = await api.verifyVendor(category, vendor);
      const environment = envStatus() || {};
      environment.vendor_verifications ||= {};
      environment.vendor_verifications[category] ||= {};
      environment.vendor_verifications[category][vendor] = result;
      setEnvStatus(environment);
    } catch (error) {
      console.error('Vendor verification failed', error);
    } finally {
      renderCategory(category);
    }
  }

  function move(category, index, offset) {
    const rows = state[category];
    const target = index + offset;
    if (target < 0 || target >= rows.length) return;
    [rows[index], rows[target]] = [rows[target], rows[index]];
    save();
    renderCategory(category);
  }

  function formatHealth(status) {
    return {
      available: t('vendorAvailable'), unavailable: t('vendorUnavailable'),
      no_data: t('vendorNoData'), rate_limited: t('vendorRateLimited'),
      not_configured: t('vendorNotConfigured'), unverified: t('vendorNeverVerified'),
    }[status] || t('vendorUnavailable');
  }

  function formatVerification(verification) {
    if (!verification?.verified_at) return t('vendorNeverVerified');
    const source = verification.source === 'manual' ? t('vendorVerifiedManual') : t('vendorVerifiedAnalysis');
    const time = new Intl.DateTimeFormat(locale() === 'zh' ? 'zh-CN' : 'en', {
      dateStyle: 'short', timeStyle: 'medium',
    }).format(new Date(verification.verified_at));
    const latency = Number.isFinite(verification.latency_ms) ? ` · ${verification.latency_ms} ms` : '';
    return `${source} · ${time}${latency}`;
  }

  function renderOhlcvTable() {
    if (!ohlcvSettingsBody) return;
    const environment = envStatus();
    const rows = state.core_stock_apis || CATEGORY_VENDORS.core_stock_apis.map(id => ({ id, enabled: false }));
    ohlcvSettingsBody.innerHTML = rows.map((setting, index) => {
      const meta = PROVIDER_META[setting.id] || { name: setting.id };
      const credential = credentialStatus(environment?.data_vendors?.[setting.id]);
      return `<tr>
        <td><strong>${escapeHtml(meta.name)}</strong></td>
        <td>${index + 1}</td>
        <td><span class="badge ${setting.enabled ? 'quality-high' : 'quality-neutral'}">${escapeHtml(setting.enabled ? t('providerEnabled') : t('providerDisabled'))}</span></td>
        <td>${escapeHtml(credential.label)}</td>
      </tr>`;
    }).join('');
  }

  function current() {
    return Object.fromEntries(Object.entries(state).map(([category, vendors]) => [
      category,
      vendors.filter(vendor => vendor.enabled).map(vendor => vendor.id).join(', '),
    ]));
  }

  function snapshot() {
    return JSON.parse(JSON.stringify(state));
  }

  return { load, reset, refresh, current, snapshot };
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
