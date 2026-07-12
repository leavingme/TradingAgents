async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  return response;
}

export const api = {
  async startRun(payload) {
    const response = await request('/api/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return response.json();
  },
  async listRuns() {
    return (await request('/api/runs')).json();
  },
  async getRun(runId) {
    return (await request(`/api/runs/${encodeURIComponent(runId)}`)).json();
  },
  async cancelRun(runId) {
    await request(`/api/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' });
  },
  async deleteRun(runId) {
    await request(`/api/runs/${encodeURIComponent(runId)}`, { method: 'DELETE' });
  },
  async clearRuns() {
    await request('/api/runs', { method: 'DELETE' });
  },
  async getReport(runId) {
    return (await request(`/api/runs/${encodeURIComponent(runId)}/report`)).text();
  },
  async getConfigDefaults() {
    return (await request('/api/config/defaults')).json();
  },
  async getWebConfig() {
    return (await request('/api/config/web')).json();
  },
  async saveWebConfig(payload) {
    return (await request('/api/config/web', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })).json();
  },
  async resetWebConfig() {
    return (await request('/api/config/web', { method: 'DELETE' })).json();
  },
  async getEnvStatus() {
    return (await request('/api/config/env-status')).json();
  },
  async getAnalystPrompts() {
    return (await request('/api/config/analyst-prompts')).json();
  },
  async verifyVendor(category, vendor) {
    return (await request(
      `/api/config/data-vendors/${encodeURIComponent(category)}/${encodeURIComponent(vendor)}/verify`,
      { method: 'POST' },
    )).json();
  },
};
