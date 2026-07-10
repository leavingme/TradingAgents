#!/usr/bin/env node
const port = process.argv[2];
if (!port) throw new Error('usage: node scripts/audit_frontend_layout.mjs <debug-port>');

await new Promise(resolve => setTimeout(resolve, 1000));
const targets = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = targets.find(target => target.type === 'page');
if (!page) throw new Error('no Chrome page target found');

const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});

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
  providerRows: document.querySelectorAll('.provider-item').length,
  historyRows: document.querySelectorAll('#historyList > li').length,
  reportPlaceholder: Boolean(document.querySelector('.report-empty')),
})`;

socket.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression, returnByValue: true } }));
const result = await new Promise((resolve, reject) => {
  socket.addEventListener('message', event => {
    const payload = JSON.parse(event.data);
    if (payload.id !== 1) return;
    if (payload.error || payload.result?.exceptionDetails) reject(new Error(JSON.stringify(payload)));
    else resolve(payload.result.result.value);
  });
});
socket.close();
console.log(result);
