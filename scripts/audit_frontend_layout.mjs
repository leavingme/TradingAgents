#!/usr/bin/env node
const port = process.argv[2];
const emulatedWidth = process.argv[3] ? Number(process.argv[3]) : null;
const emulatedHeight = process.argv[4] ? Number(process.argv[4]) : null;
if (!port) throw new Error(
  'usage: node scripts/audit_frontend_layout.mjs <debug-port> [width height]'
);

await new Promise(resolve => setTimeout(resolve, 1000));
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(target => target.type === 'page');
if (!page) throw new Error('no Chrome page target found');

const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
socket.addEventListener('error', reject, { once: true });
});

const waitForId = id => new Promise((resolve, reject) => {
  const listener = event => {
    const payload = JSON.parse(event.data);
    if (payload.id !== id) return;
    socket.removeEventListener('message', listener);
    if (payload.error || payload.result?.exceptionDetails) reject(new Error(JSON.stringify(payload)));
    else resolve(payload);
  };
  socket.addEventListener('message', listener);
});

if (emulatedWidth && emulatedHeight) {
  socket.send(JSON.stringify({
    id: 1,
    method: 'Emulation.setDeviceMetricsOverride',
    params: {
      width: emulatedWidth,
      height: emulatedHeight,
      deviceScaleFactor: 1,
      mobile: true,
    },
  }));
  await waitForId(1);
  await new Promise(resolve => setTimeout(resolve, 250));
}

const expression = `JSON.stringify({
  readyState: document.readyState,
  hash: location.hash,
  scroll: { x: window.scrollX, y: window.scrollY },
  viewport: { width: document.documentElement.clientWidth, height: document.documentElement.clientHeight },
  documentScrollWidth: document.documentElement.scrollWidth,
  bodyScrollWidth: document.body.scrollWidth,
  horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  runHidden: document.querySelector('#runView').hidden,
  settingsHidden: document.querySelector('#settingsView').hidden,
  providersHidden: document.querySelector('#providersView').hidden,
  evaluationsHidden: document.querySelector('#evaluationsView').hidden,
  evaluationCards: document.querySelectorAll('.evaluation-card').length,
  evaluationText: document.querySelector('#evaluationRollups')?.textContent?.trim().slice(0, 500) || '',
  providerRows: document.querySelectorAll('.provider-item').length,
  historyRows: document.querySelectorAll('#historyList > li').length,
  reportPlaceholder: Boolean(document.querySelector('.report-empty')),
})`;

socket.send(JSON.stringify({ id: 2, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
const result = await new Promise((resolve, reject) => {
  socket.addEventListener('message', event => {
    const payload = JSON.parse(event.data);
    if (payload.id !== 2) return;
    if (payload.error || payload.result?.exceptionDetails) reject(new Error(JSON.stringify(payload)));
    else resolve(payload.result.result.value);
  });
});
socket.close();
console.log(result);
