import readline from 'node:readline';
import process from 'node:process';
import fs from 'node:fs';

const CSI = '\x1b[';
const ENTER_ALT_SCREEN = '\x1b[?1049h';
const EXIT_ALT_SCREEN = '\x1b[?1049l';
const HIDE_CURSOR = '\x1b[?25l';
const SHOW_CURSOR = '\x1b[?25h';
const ENABLE_INPUT_REPORTING = [
  '\x1b[?1000h', // X10 mouse
  '\x1b[?1002h', // button-event mouse
  '\x1b[?1006h', // SGR mouse
].join('');
const DISABLE_INPUT_REPORTING = [
  '\x1b[?1000l', // X10 mouse
  '\x1b[?1002l', // button-event mouse
  '\x1b[?1003l', // any-event mouse
  '\x1b[?1004l', // focus events
  '\x1b[?1005l', // UTF-8 mouse
  '\x1b[?1006l', // SGR mouse
  '\x1b[?1015l', // urxvt mouse
  '\x1b[?2004l', // bracketed paste
].join('');
const ERASE_SCREEN = `${CSI}2J`;
const CURSOR_HOME = `${CSI}H`;
const ERASE_LINE = `${CSI}2K`;
const BSU = '\x1b[?2026h';
const ESU = '\x1b[?2026l';
const SPINNER_FRAMES = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];
const RESET = '\x1b[0m';
const STYLES = {
  boldGreen: '\x1b[1;32m',
  dim: '\x1b[2m',
  cyan: '\x1b[36m',
  boldCyan: '\x1b[1;36m',
  blue: '\x1b[34m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  red: '\x1b[31m',
  white: '\x1b[37m',
  boldWhite: '\x1b[1;37m',
  reverse: '\x1b[7m',
  magentaBold: '\x1b[1;35m',
  grey: '\x1b[90m',
  italic: '\x1b[3m',
};

const state = {
  mode: 'dashboard',
  spinnerText: 'Preparing analysis...',
  startTime: Date.now() / 1000,
  agentStatus: {},
  messages: [],
  currentReport: null,
  stats: null,
  reportsCompleted: 0,
  reportsTotal: 0,
  reportScroll: 0,
  messageScroll: 0,
  viewerTitle: 'Complete Report',
  viewerContent: '',
  viewerScroll: 0,
};

let spinnerIndex = 0;
let previousScreen = null;
let disposed = false;
let ttyInput = null;
let lastLayout = null;

class Cell {
  constructor(char = ' ', style = '') {
    this.char = char;
    this.style = style;
  }

  equals(other) {
    return other && this.char === other.char && this.style === other.style;
  }
}

class Screen {
  constructor(width, height) {
    this.width = width;
    this.height = height;
    this.cells = Array.from({ length: height }, () =>
      Array.from({ length: width }, () => new Cell()),
    );
  }

  write(x, y, text, style = '') {
    if (y < 0 || y >= this.height || x >= this.width) return;
    let col = Math.max(0, x);
    for (const char of String(text)) {
      if (col >= this.width) break;
      const width = charWidth(char);
      if (width === 0) {
        if (col > 0) this.cells[y][col - 1].char += char;
        continue;
      }
      if (col + width > this.width) break;
      this.cells[y][col] = new Cell(char, style);
      if (width === 2 && col + 1 < this.width) {
        this.cells[y][col + 1] = new Cell('', style);
      }
      col += width;
    }
  }

  line(y) {
    return this.cells[y].map(cell => cell.char).join('').trimEnd();
  }
}

function styledText(cells) {
  let output = '';
  let currentStyle = '';
  for (const cell of cells) {
    if (cell.style !== currentStyle) {
      output += cell.style || RESET;
      currentStyle = cell.style;
    }
    output += cell.char;
  }
  if (currentStyle) output += RESET;
  return output;
}

function termSize() {
  return {
    width: Math.max(60, process.stdout.columns || 100),
    height: Math.max(18, process.stdout.rows || 30),
  };
}

function charWidth(char) {
  if (!char) return 0;
  const code = char.codePointAt(0);
  if (
    (code >= 0x0300 && code <= 0x036f) ||
    (code >= 0x1ab0 && code <= 0x1aff) ||
    (code >= 0x1dc0 && code <= 0x1dff) ||
    (code >= 0x20d0 && code <= 0x20ff) ||
    (code >= 0xfe20 && code <= 0xfe2f)
  ) {
    return 0;
  }
  if (
    (code >= 0x1100 && code <= 0x115f) ||
    code === 0x2329 ||
    code === 0x232a ||
    (code >= 0x2e80 && code <= 0xa4cf) ||
    (code >= 0xac00 && code <= 0xd7a3) ||
    (code >= 0xf900 && code <= 0xfaff) ||
    (code >= 0xfe10 && code <= 0xfe19) ||
    (code >= 0xfe30 && code <= 0xfe6f) ||
    (code >= 0xff00 && code <= 0xff60) ||
    (code >= 0xffe0 && code <= 0xffe6) ||
    (code >= 0x1f300 && code <= 0x1faff)
  ) {
    return 2;
  }
  return 1;
}

function combineStyles(...styles) {
  return styles.filter(Boolean).join('');
}

function displayWidth(text) {
  return Array.from(String(text ?? '')).reduce((total, char) => total + charWidth(char), 0);
}

function clip(text, width) {
  let used = 0;
  let output = '';
  for (const char of String(text ?? '')) {
    const w = charWidth(char);
    if (used + w > width) break;
    output += char;
    used += w;
  }
  return output;
}

function pad(text, width) {
  const clipped = clip(text, width);
  return clipped + ' '.repeat(Math.max(0, width - displayWidth(clipped)));
}

function center(text, width) {
  const clipped = clip(text, width);
  const left = Math.max(0, Math.floor((width - displayWidth(clipped)) / 2));
  return ' '.repeat(left) + pad(clipped, width - left);
}

function sanitize(text) {
  return String(text ?? '').replace(/\s+/g, ' ').trim();
}

function wrap(text, width, maxLines) {
  const words = sanitize(text).split(' ').filter(Boolean);
  const lines = [];
  let current = '';
  for (const word of words) {
    if (lines.length >= maxLines) break;
    if (!current) {
      current = word;
    } else if (displayWidth(`${current} ${word}`) <= width) {
      current += ` ${word}`;
    } else {
      lines.push(clip(current, width));
      current = word;
    }
  }
  if (current && lines.length < maxLines) lines.push(clip(current, width));
  return lines;
}

function stripInlineMarkdown(text) {
  return String(text ?? '')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/`([^`]+)`/g, '$1');
}

function cleanDisplayText(text) {
  return stripInlineMarkdown(text)
    .replace(/[“”][\s\u00a0]*[“”]/g, '')
    .replace(/["'][\s\u00a0]*["']/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function stripMarkdown(markdown) {
  let inFence = false;
  const lines = [];
  for (const raw of String(markdown ?? '').split('\n')) {
    let line = raw.trimEnd();
    if (line.trimStart().startsWith('```')) {
      inFence = !inFence;
      continue;
    }
    if (!inFence) {
      line = line.replace(/^\s{0,3}#{1,6}\s*/, '');
      line = line.replace(/\*\*([^*]+)\*\*/g, '$1');
      line = line.replace(/\*([^*]+)\*/g, '$1');
      line = line.replace(/`([^`]+)`/g, '$1');
    }
    lines.push(line);
  }
  return lines.join('\n').trim();
}

function colorForStatus(status) {
  if (status === 'completed') return STYLES.green;
  if (status === 'error') return STYLES.red;
  if (status === 'pending') return STYLES.yellow;
  return STYLES.white;
}

function box(screen, x, y, width, height, title, body, options = {}) {
  if (width < 4 || height < 3) return;
  const borderStyle = options.borderStyle || '';
  const titleStyle = options.titleStyle || borderStyle;
  const paddingX = options.paddingX ?? 2;
  const paddingY = options.paddingY ?? 1;
  const titleText = title ? ` ${title} ` : '';
  screen.write(x, y, '╭', borderStyle);
  screen.write(x + 1, y, titleText, titleStyle);
  screen.write(
    x + 1 + titleText.length,
    y,
    '─'.repeat(Math.max(0, width - 2 - titleText.length)),
    borderStyle,
  );
  screen.write(x + width - 1, y, '╮', borderStyle);
  for (let row = 1; row < height - 1; row += 1) {
    screen.write(x, y + row, '│', borderStyle);
    screen.write(x + width - 1, y + row, '│', borderStyle);
  }
  screen.write(x, y + height - 1, '╰' + '─'.repeat(width - 2) + '╯', borderStyle);

  const innerWidth = width - 2 - paddingX * 2;
  const maxBody = height - 2 - paddingY * 2;
  for (let idx = 0; idx < Math.min(body.length, maxBody); idx += 1) {
    const line = body[idx];
    const row = y + 1 + paddingY + idx;
    const col = x + 1 + paddingX;
    if (Array.isArray(line)) {
      let offset = 0;
      for (const segment of line) {
        const text = clip(segment.text, innerWidth - offset);
        screen.write(col + offset, row, text, segment.style || '');
        offset += displayWidth(text);
        if (offset >= innerWidth) break;
      }
    } else {
      screen.write(col, row, pad(line, innerWidth));
    }
  }
}

function progressLines(width, height) {
  const teams = {
    'Analyst Team': ['Market Analyst', 'Sentiment Analyst', 'News Analyst', 'Fundamentals Analyst'],
    'Research Team': ['Bull Researcher', 'Bear Researcher', 'Research Manager'],
    'Trading Team': ['Trader'],
    'Risk Management': ['Aggressive Analyst', 'Neutral Analyst', 'Conservative Analyst'],
    'Portfolio Management': ['Portfolio Manager'],
  };
  const lines = [];
  const spinner = SPINNER_FRAMES[spinnerIndex % SPINNER_FRAMES.length];
  const usable = Math.max(28, width - 4);
  const gap = ' ';
  const activeTeamNames = Object.entries(teams)
    .filter(([_team, agents]) => agents.some(agent => agent in state.agentStatus))
    .map(([team]) => team);
  const longestTeam = Math.max(4, ...activeTeamNames.map(team => displayWidth(team)));
  const statusW = Math.min(15, Math.max(13, Math.floor(usable * 0.25)));
  const teamW = Math.min(Math.max(12, longestTeam), Math.max(8, usable - statusW - 8 - gap.length * 2));
  const agentW = Math.max(10, usable - teamW - statusW - gap.length * 2);

  lines.push([
    { text: center('Team', teamW), style: STYLES.magentaBold },
    { text: gap },
    { text: center('Agent', agentW), style: STYLES.magentaBold },
    { text: gap },
    { text: center('Status', statusW), style: STYLES.magentaBold },
  ]);
  lines.push([{ text: '─'.repeat(Math.min(usable, teamW + agentW + statusW + gap.length * 2)), style: STYLES.dim }]);

  for (const [team, agents] of Object.entries(teams)) {
    const active = agents.filter(agent => agent in state.agentStatus);
    if (active.length === 0) continue;
    active.forEach((agent, idx) => {
      const status = state.agentStatus[agent] || 'pending';
      const statusText = status === 'in_progress' ? `${spinner} in_progress` : status;
      lines.push([
        { text: center(idx === 0 ? team : '', teamW), style: STYLES.cyan },
        { text: gap },
        { text: center(agent, agentW), style: STYLES.green },
        { text: gap },
        {
          text: center(statusText, statusW),
          style: status === 'in_progress' ? STYLES.boldCyan : colorForStatus(status),
        },
      ]);
    });
    lines.push([{ text: '─'.repeat(Math.min(usable, teamW + agentW + statusW + gap.length * 2)), style: STYLES.dim }]);
  }
  return lines.slice(0, Math.max(0, height - 2));
}

function messageLines(width, height) {
  const usable = Math.max(20, width - 6);
  const timeW = 8;
  const typeW = 10;
  const contentW = Math.max(8, usable - timeW - typeW - 4);
  const lines = [
    [
      { text: center('Time', timeW), style: STYLES.magentaBold },
      { text: '  ' },
      { text: center('Type', typeW), style: STYLES.magentaBold },
      { text: '  ' },
      { text: 'Content', style: STYLES.magentaBold },
    ],
  ];
  const visibleMessages = state.messages.slice(
    state.messageScroll,
    state.messageScroll + Math.max(0, height - 4),
  );
  for (const item of visibleMessages) {
    lines.push([
      { text: center(item.time, timeW), style: STYLES.cyan },
      { text: '  ' },
      { text: center(item.type, typeW), style: STYLES.green },
      { text: '  ' },
      { text: clip(sanitize(item.content), contentW), style: STYLES.white },
    ]);
    lines.push([{ text: '─'.repeat(usable), style: STYLES.dim }]);
  }
  return lines.slice(0, Math.max(0, height - 2));
}

function isTableRow(line) {
  return /^\s*\|(.+)\|\s*$/.test(line);
}

function tableCells(line) {
  const match = line.match(/^\s*\|(.+)\|\s*$/);
  if (!match) return [];
  return match[1].split('|').map(cell => cleanDisplayText(cell));
}

function isTableSeparator(line) {
  const cells = tableCells(line);
  return cells.length > 0 && cells.every(cell => /^:?-{3,}:?$/.test(cell));
}

function tableAligns(line, colCount) {
  const cells = tableCells(line);
  return Array.from({ length: colCount }, (_v, index) => {
    const cell = cells[index] || '';
    const left = cell.startsWith(':');
    const right = cell.endsWith(':');
    if (left && right) return 'center';
    if (right) return 'right';
    return 'left';
  });
}

function alignCell(text, width, align = 'left') {
  const clipped = clip(text, width);
  const remaining = Math.max(0, width - displayWidth(clipped));
  if (align === 'right') return `${' '.repeat(remaining)}${clipped}`;
  if (align === 'center') {
    const left = Math.floor(remaining / 2);
    return `${' '.repeat(left)}${clipped}${' '.repeat(remaining - left)}`;
  }
  return `${clipped}${' '.repeat(remaining)}`;
}

function wrapLine(text, width, style = '', prefix = '', continuationPrefix = null) {
  const firstPrefix = prefix;
  const nextPrefix = continuationPrefix ?? ' '.repeat(displayWidth(prefix));
  const result = [];
  const clean = cleanDisplayText(text);
  if (!clean) return [];

  let remaining = clean;
  let currentPrefix = firstPrefix;
  while (remaining) {
    const available = Math.max(1, width - displayWidth(currentPrefix));
    let chunk = clip(remaining, available);
    if (displayWidth(remaining) > available) {
      const breakAt = chunk.lastIndexOf(' ');
      if (breakAt > 8) chunk = chunk.slice(0, breakAt);
    }
    result.push([
      { text: currentPrefix, style: prefix ? STYLES.dim : style },
      { text: chunk.trimEnd(), style },
    ]);
    remaining = remaining.slice(chunk.length).trimStart();
    currentPrefix = nextPrefix;
  }
  return result;
}

function tableLines(rows, width) {
  const parsed = rows.map(tableCells);
  const separatorIndex = parsed.findIndex((_row, idx) => isTableSeparator(rows[idx]));
  const dataRows = parsed.filter((_row, idx) => idx !== separatorIndex);
  if (dataRows.length === 0) return [];

  const colCount = Math.max(...dataRows.map(row => row.length));
  const aligns = separatorIndex >= 0 ? tableAligns(rows[separatorIndex], colCount) : Array.from({ length: colCount }, () => 'left');
  const minCol = 3;
  const borderOverhead = colCount * 3 + 1;
  const available = Math.max(colCount * minCol, width - borderOverhead);
  const natural = Array.from({ length: colCount }, (_v, col) =>
    Math.max(
      minCol,
      ...dataRows.map(row => displayWidth(row[col] ?? '')),
    ),
  );
  let colWidths = [...natural];
  let total = colWidths.reduce((sum, value) => sum + value, 0);
  while (total > available) {
    const idx = colWidths.indexOf(Math.max(...colWidths));
    if (colWidths[idx] <= minCol) break;
    colWidths[idx] -= 1;
    total -= 1;
  }

  const line = (left, fill, join, right) => [
    { text: left, style: STYLES.dim },
    ...colWidths.flatMap((colWidth, index) => [
      { text: fill.repeat(colWidth + 2), style: STYLES.dim },
      { text: index === colWidths.length - 1 ? right : join, style: STYLES.dim },
    ]),
  ];

  const rowSegments = (row, style) => {
    const segments = [{ text: '│', style: STYLES.dim }];
    for (let col = 0; col < colCount; col += 1) {
      segments.push({ text: ' ', style: STYLES.dim });
      segments.push({
        text: alignCell(row[col] ?? '', colWidths[col], aligns[col]),
        style,
      });
      segments.push({ text: ' │', style: STYLES.dim });
    }
    return segments;
  };

  const output = [];
  output.push(line('╭', '─', '┬', '╮'));
  dataRows.forEach((row, rowIndex) => {
    const isHeader = separatorIndex === 1 && rowIndex === 0;
    output.push(rowSegments(row, isHeader ? STYLES.boldWhite : ''));
    if (isHeader) {
      output.push(line('├', '─', '┼', '┤'));
    }
  });
  output.push(line('╰', '─', '┴', '╯'));
  return output;
}

function markdownLines(markdown, width, maxLines) {
  let inFence = false;
  const lines = [];
  const rawLines = String(markdown ?? '').split('\n');
  for (let index = 0; index < rawLines.length;) {
    if (lines.length >= maxLines) break;
    const raw = rawLines[index];
    let line = raw.trimEnd();
    if (line.trimStart().startsWith('```')) {
      inFence = !inFence;
      if (inFence) {
        const language = line.trim().slice(3).trim();
        lines.push([{ text: language ? `Code (${language})` : 'Code', style: STYLES.dim }]);
      }
      index += 1;
      continue;
    }
    if (inFence) {
        lines.push([{ text: clip(`  ${line}`, width), style: STYLES.dim }]);
      index += 1;
      continue;
    }
    if (!line.trim()) {
      lines.push('');
      index += 1;
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
    if (heading) {
      const level = heading[1].length;
      const text = cleanDisplayText(heading[2]);
      if (!text) {
        index += 1;
        continue;
      }
      if (lines.length > 0 && lines[lines.length - 1] !== '') lines.push('');
      lines.push([{ text: clip(text, width), style: level <= 2 ? STYLES.boldGreen : STYLES.boldWhite }]);
      if (level <= 2) {
        lines.push([{ text: '─'.repeat(Math.min(width, Math.max(8, displayWidth(text)))), style: STYLES.dim }]);
      }
      index += 1;
      continue;
    }

    if (isTableRow(line)) {
      const rows = [];
      while (index < rawLines.length && isTableRow(rawLines[index])) {
        rows.push(rawLines[index].trimEnd());
        index += 1;
      }
      lines.push(...tableLines(rows, width).slice(0, maxLines - lines.length));
      continue;
    }

    const quote = line.match(/^\s{0,3}>\s?(.*)$/);
    if (quote) {
      lines.push(...wrapLine(quote[1], width, combineStyles(STYLES.dim, STYLES.italic), '┃ ', '┃ '));
      index += 1;
      continue;
    }

    const unordered = line.match(/^(\s*)[-*+]\s+(.*)$/);
    if (unordered) {
      const depth = Math.min(3, Math.floor(unordered[1].length / 2));
      const prefix = `${'  '.repeat(depth)}• `;
      lines.push(...wrapLine(unordered[2], width, '', prefix));
      index += 1;
      continue;
    }

    const ordered = line.match(/^(\s*)(\d+)[.)]\s+(.*)$/);
    if (ordered) {
      const depth = Math.min(3, Math.floor(ordered[1].length / 2));
      const prefix = `${'  '.repeat(depth)}${ordered[2]}. `;
      lines.push(...wrapLine(ordered[3], width, '', prefix));
      index += 1;
      continue;
    }

    const rule = line.match(/^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/);
    if (rule) {
      lines.push([{ text: '─'.repeat(width), style: STYLES.dim }]);
      index += 1;
      continue;
    }

    lines.push(...wrapLine(line, width, ''));
    index += 1;
  }
  return lines;
}

function allReportLines(width) {
  if (!state.currentReport) {
    return [[{ text: 'Waiting for analysis report...', style: STYLES.italic }]];
  }
  return markdownLines(state.currentReport, width - 6, 10000);
}

function allViewerLines(width) {
  return markdownLines(state.viewerContent, width - 6, 100000);
}

function viewerLines(width, height) {
  const maxVisible = Math.max(0, height - 4);
  const body = allViewerLines(width);
  const contentVisible = body.length > maxVisible ? Math.max(0, maxVisible - 1) : maxVisible;
  const maxScroll = Math.max(0, body.length - contentVisible);
  state.viewerScroll = Math.min(Math.max(0, state.viewerScroll), maxScroll);
  const visible = body.slice(state.viewerScroll, state.viewerScroll + contentVisible);
  if (body.length > maxVisible) {
    const marker = `${state.viewerScroll + 1}-${state.viewerScroll + visible.length}/${body.length}  q/Esc to close`;
    const markerWidth = Math.max(0, width - 6);
    visible.push([{ text: `${' '.repeat(Math.max(0, markerWidth - displayWidth(marker)))}${marker}`, style: STYLES.dim }]);
  } else {
    visible.push([{ text: 'q/Esc to close', style: STYLES.dim }]);
  }
  return visible;
}

function reportLines(width, height) {
  const maxVisible = Math.max(0, height - 4);
  const body = allReportLines(width);
  const contentVisible = body.length > maxVisible ? Math.max(0, maxVisible - 1) : maxVisible;
  const maxScroll = Math.max(0, body.length - contentVisible);
  state.reportScroll = Math.min(Math.max(0, state.reportScroll), maxScroll);
  const visible = body.slice(state.reportScroll, state.reportScroll + contentVisible);
  if (body.length > maxVisible) {
    const marker = `${state.reportScroll + 1}-${state.reportScroll + visible.length}/${body.length}`;
    const markerWidth = Math.max(0, width - 6);
    visible.push([{ text: `${' '.repeat(Math.max(0, markerWidth - displayWidth(marker)))}${marker}`, style: STYLES.dim }]);
  }
  return visible;
}

function statsLine() {
  const statuses = Object.values(state.agentStatus);
  const completed = statuses.filter(status => status === 'completed').length;
  const parts = [`Agents: ${completed}/${statuses.length}`];
  if (state.stats) {
    parts.push(`LLM: ${state.stats.llm_calls}`);
    parts.push(`Tools: ${state.stats.tool_calls}`);
    if (state.stats.tokens_in > 0 || state.stats.tokens_out > 0) {
      parts.push(`Tokens: ${formatTokens(state.stats.tokens_in)}↑ ${formatTokens(state.stats.tokens_out)}↓`);
    } else {
      parts.push('Tokens: --');
    }
  }
  parts.push(`Reports: ${state.reportsCompleted}/${state.reportsTotal}`);
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - state.startTime));
  parts.push(`⏱ ${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`);
  return parts.join(' | ');
}

function footerLines(width) {
  return [[{ text: center(statsLine(), width - 6), style: STYLES.white }]];
}

function writeCentered(screen, x, y, width, segments) {
  const textLength = segments.reduce((acc, segment) => acc + displayWidth(segment.text), 0);
  let offset = Math.max(0, Math.floor((width - textLength) / 2));
  for (const segment of segments) {
    screen.write(x + offset, y, segment.text, segment.style || '');
    offset += displayWidth(segment.text);
  }
}

function drawHeader(screen, width) {
  box(screen, 0, 0, width, 3, 'Welcome to TradingAgents', [], {
    borderStyle: STYLES.green,
    titleStyle: STYLES.green,
    paddingX: 2,
    paddingY: 0,
  });
  writeCentered(screen, 2, 1, width - 4, [
    { text: 'Welcome to TradingAgents CLI', style: STYLES.boldGreen },
    { text: '  ' },
    { text: '© Tauric Research', style: STYLES.dim },
  ]);
}

function formatTokens(n) {
  if (!Number.isFinite(n)) return '0';
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function renderFrame() {
  const { width, height } = termSize();
  const screen = new Screen(width, height);

  if (state.mode === 'viewer') {
    lastLayout = {
      report: { x: 0, y: 0, width, height },
      messages: null,
    };
    box(screen, 0, 0, width, height, state.viewerTitle || 'Complete Report', viewerLines(width, height), {
      borderStyle: STYLES.green,
      titleStyle: STYLES.green,
      paddingX: 2,
      paddingY: 1,
    });
    return screen;
  }

  const headerHeight = 3;
  const footerHeight = 3;
  const mainHeight = height - headerHeight - footerHeight;
  const upperHeight = Math.max(8, Math.floor(mainHeight * 3 / 8));
  const reportHeight = Math.max(5, mainHeight - upperHeight);
  const leftWidth = Math.floor((width - 1) / 2);
  const rightWidth = width - leftWidth - 1;
  lastLayout = {
    messages: { x: leftWidth + 1, y: headerHeight, width: rightWidth, height: upperHeight },
    report: { x: 0, y: headerHeight + upperHeight, width, height: reportHeight },
  };

  drawHeader(screen, width);
  box(screen, 0, headerHeight, leftWidth, upperHeight, 'Progress', progressLines(leftWidth, upperHeight), {
    borderStyle: STYLES.cyan,
    titleStyle: STYLES.cyan,
    paddingX: 1,
    paddingY: 1,
  });
  box(screen, leftWidth + 1, headerHeight, rightWidth, upperHeight, 'Messages & Tools', messageLines(rightWidth, upperHeight), {
    borderStyle: STYLES.blue,
    titleStyle: STYLES.blue,
    paddingX: 2,
    paddingY: 1,
  });
  box(screen, 0, headerHeight + upperHeight, width, reportHeight, 'Current Report', reportLines(width, reportHeight), {
    borderStyle: STYLES.green,
    titleStyle: STYLES.green,
    paddingX: 2,
    paddingY: 1,
  });
  box(screen, 0, height - footerHeight, width, footerHeight, '', footerLines(width), {
    borderStyle: STYLES.grey,
    paddingX: 2,
    paddingY: 0,
  });
  return screen;
}

function cellDiff(prev, next) {
  if (!prev || prev.width !== next.width || prev.height !== next.height) {
    const patches = [ERASE_SCREEN, CURSOR_HOME];
    for (let y = 0; y < next.height; y += 1) {
      patches.push(`${CSI}${y + 1};1H${ERASE_LINE}${styledText(next.cells[y])}`);
    }
    return patches;
  }

  const patches = [];
  for (let y = 0; y < next.height; y += 1) {
    let runStart = -1;
    let run = [];
    for (let x = 0; x < next.width; x += 1) {
      const nextCell = next.cells[y][x];
      const prevCell = prev.cells[y][x];
      if (nextCell.char === '') {
        continue;
      }
      if (nextCell.equals(prevCell)) {
        if (runStart >= 0) {
          patches.push(`${CSI}${y + 1};${runStart + 1}H${styledText(run)}`);
          runStart = -1;
          run = [];
        }
        continue;
      }
      if (runStart < 0) runStart = x;
      run.push(nextCell);
    }
    if (runStart >= 0) patches.push(`${CSI}${y + 1};${runStart + 1}H${styledText(run)}`);
  }
  return patches;
}

function paint() {
  if (disposed || !process.stdout.isTTY) return;
  const next = renderFrame();
  const patches = cellDiff(previousScreen, next);
  if (patches.length > 0) {
    process.stdout.write(BSU + patches.join('') + ESU);
  }
  previousScreen = next;
}

function applyState(nextState) {
  Object.assign(state, nextState);
  if (!state.startTime) state.startTime = Date.now() / 1000;
  state.messageScroll = Math.min(Math.max(0, state.messageScroll), Math.max(0, state.messages.length - 1));
  paint();
}

function pointIn(rect, x, y) {
  return rect && x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height;
}

function scrollReport(delta) {
  if (state.mode === 'viewer') {
    scrollViewer(delta);
    return;
  }
  const { height, width } = termSize();
  const headerHeight = 3;
  const footerHeight = 3;
  const mainHeight = height - headerHeight - footerHeight;
  const upperHeight = Math.max(8, Math.floor(mainHeight * 3 / 8));
  const reportHeight = Math.max(5, mainHeight - upperHeight);
  const maxVisible = Math.max(0, reportHeight - 4);
  const maxScroll = Math.max(0, allReportLines(width).length - maxVisible);
  const next = Math.min(Math.max(0, state.reportScroll + delta), maxScroll);
  if (next !== state.reportScroll) {
    state.reportScroll = next;
    paint();
  }
}

function scrollViewer(delta) {
  const { height, width } = termSize();
  const maxVisible = Math.max(0, height - 4);
  const contentVisible = allViewerLines(width).length > maxVisible ? Math.max(0, maxVisible - 1) : maxVisible;
  const maxScroll = Math.max(0, allViewerLines(width).length - contentVisible);
  const next = Math.min(Math.max(0, state.viewerScroll + delta), maxScroll);
  if (next !== state.viewerScroll) {
    state.viewerScroll = next;
    paint();
  }
}

function scrollMessages(delta) {
  const maxScroll = Math.max(0, state.messages.length - 1);
  const next = Math.min(Math.max(0, state.messageScroll + delta), maxScroll);
  if (next !== state.messageScroll) {
    state.messageScroll = next;
    paint();
  }
}

function handleInput(chunk) {
  const data = chunk.toString('utf8');
  if (state.mode === 'viewer' && (data === 'q' || data === 'Q' || data === '\x1b' || data.includes('\r') || data.includes('\n'))) {
    dispose();
    process.exit(0);
  }
  const sgrMouse = /\x1b\[<(\d+);(\d+);(\d+)([mM])/g;
  let match;
  while ((match = sgrMouse.exec(data)) !== null) {
    const button = Number(match[1]);
    const x = Number(match[2]) - 1;
    const y = Number(match[3]) - 1;
    if (button !== 64 && button !== 65) continue;
    const delta = button === 64 ? -3 : 3;
    if (pointIn(lastLayout?.messages, x, y)) scrollMessages(delta);
    else scrollReport(delta);
  }

  if (data.includes('\x1b[A')) scrollReport(-3);
  if (data.includes('\x1b[B')) scrollReport(3);
  if (data.includes('\x1b[5~')) scrollReport(-10);
  if (data.includes('\x1b[6~')) scrollReport(10);
}

function dispose() {
  if (disposed) return;
  disposed = true;
  clearInterval(timer);
  if (ttyInput) {
    ttyInput.off('data', handleInput);
    ttyInput.destroy();
    ttyInput = null;
  }
  process.stdout.write(DISABLE_INPUT_REPORTING + SHOW_CURSOR + EXIT_ALT_SCREEN);
}

process.stdout.write(DISABLE_INPUT_REPORTING + ENABLE_INPUT_REPORTING + ENTER_ALT_SCREEN + HIDE_CURSOR + ERASE_SCREEN + CURSOR_HOME);

try {
  ttyInput = fs.createReadStream('/dev/tty', { encoding: 'utf8' });
  ttyInput.on('data', handleInput);
} catch {
  ttyInput = null;
}

const timer = setInterval(() => {
  spinnerIndex = (spinnerIndex + 1) % SPINNER_FRAMES.length;
  paint();
}, 250);

process.stdout.on('resize', () => {
  previousScreen = null;
  paint();
});

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on('line', line => {
  if (!line.trim()) return;
  let event;
  try {
    event = JSON.parse(line);
  } catch {
    return;
  }
  if (event.type === 'state') applyState(event.state || {});
  if (event.type === 'viewer') {
    Object.assign(state, {
      mode: 'viewer',
      viewerTitle: event.title || 'Complete Report',
      viewerContent: event.content || '',
      viewerScroll: 0,
    });
    previousScreen = null;
    paint();
  }
  if (event.type === 'exit') {
    dispose();
    process.exit(0);
  }
});
rl.on('close', dispose);

process.on('SIGINT', () => {
  dispose();
  process.exit(130);
});
process.on('SIGTERM', () => {
  dispose();
  process.exit(143);
});
