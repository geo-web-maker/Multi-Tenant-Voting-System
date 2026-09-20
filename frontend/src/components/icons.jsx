/* eslint-disable react-refresh/only-export-components */
import {
  TriangleAlert, LoaderCircle, CircleCheck, CircleX, Vote, ChartColumn, Siren, LockKeyhole,
  PartyPopper, Landmark, Receipt, Wallet, CalendarDays, ScrollText, ShieldAlert, ShieldCheck,
  Inbox, FolderOpen, Folder, Smartphone, Printer, Trophy, Scale, Award, Pin, Zap, Ban, Save,
  Star, Palette, Settings, Building2, Monitor, MessageCircle, BookOpen, Users, User, Search,
  Trash2, FileText, Send, Camera, ClipboardList, Mail, Eye, Pause, Play, RefreshCw, Sun, Moon,
  Lock, ArrowLeft, ArrowRight, Check, X, Plus, Minus, Circle, TrendingUp,
} from 'lucide-react';

// name -> component (+ optional per-icon props)
const ICONS = {
  warning: [TriangleAlert], loading: [LoaderCircle, { className: 'icon-spin' }],
  success: [CircleCheck], error: [CircleX], vote: [Vote], chart: [ChartColumn], alarm: [Siren],
  secure: [LockKeyhole], celebrate: [PartyPopper], institution: [Landmark], receipt: [Receipt],
  wallet: [Wallet], calendar: [CalendarDays], log: [ScrollText], danger: [ShieldAlert],
  shield: [ShieldCheck], inbox: [Inbox], folderOpen: [FolderOpen], folder: [Folder],
  phone: [Smartphone], print: [Printer], trophy: [Trophy], scale: [Scale], award: [Award],
  pin: [Pin], zap: [Zap], ban: [Ban], save: [Save], star: [Star], palette: [Palette],
  settings: [Settings], building: [Building2], monitor: [Monitor], chat: [MessageCircle],
  book: [BookOpen], users: [Users], user: [User], search: [Search], trash: [Trash2],
  file: [FileText], send: [Send], camera: [Camera], clipboard: [ClipboardList], mail: [Mail],
  eye: [Eye], pause: [Pause], play: [Play], refresh: [RefreshCw], sun: [Sun], moon: [Moon],
  lock: [Lock], back: [ArrowLeft], next: [ArrowRight], check: [Check], close: [X], plus: [Plus],
  minus: [Minus], trend: [TrendingUp],
  dot: [Circle, { fill: 'currentColor', strokeWidth: 0, style: { width: '0.55em', height: '0.55em' } }],
  dotGreen: [Circle, { fill: '#10b981', color: '#10b981', strokeWidth: 0, style: { width: '0.6em', height: '0.6em' } }],
  dotRed: [Circle, { fill: '#ef4444', color: '#ef4444', strokeWidth: 0, style: { width: '0.6em', height: '0.6em' } }],
};

// legacy glyph -> icon name (used to convert strings that still contain emoji at render time)
export const GLYPHS = {
  '⚠': 'warning', '⏳': 'loading', '✅': 'success', '❌': 'error', '🗳': 'vote', '📊': 'chart',
  '🚨': 'alarm', '🔐': 'secure', '🎉': 'celebrate', '🏛': 'institution', '🧾': 'receipt',
  '💰': 'wallet', '🗓': 'calendar', '📜': 'log', '🧨': 'danger', '🛡': 'shield', '📭': 'inbox',
  '📂': 'folderOpen', '📁': 'folder', '📱': 'phone', '🖨': 'print', '🏆': 'trophy', '⚖': 'scale',
  '🏅': 'award', '📌': 'pin', '⚡': 'zap', '🚫': 'ban', '💾': 'save', '⭐': 'star', '🎨': 'palette',
  '⚙': 'settings', '🏢': 'building', '💻': 'monitor', '💬': 'chat', '📖': 'book', '👥': 'users',
  '👤': 'user', '🔍': 'search', '🗑': 'trash', '📄': 'file', '📨': 'send', '📷': 'camera',
  '📋': 'clipboard', '📧': 'mail', '📩': 'mail', '👁': 'eye', '⏸': 'pause', '▶': 'play',
  '🔄': 'refresh', '☀': 'sun', '🌙': 'moon', '🔒': 'lock', '⬅': 'back', '➕': 'plus', '➖': 'minus',
  '📈': 'trend', '✓': 'check', '✔': 'check', '✕': 'close', '→': 'next', '←': 'back',
  '●': 'dot', '🟢': 'dotGreen', '🔴': 'dotRed',
};

export function Icon({ name, size = '1.1em', style, ...rest }) {
  const entry = ICONS[name];
  if (!entry) return null;
  const [Cmp, base = {}] = entry;
  return (
    <Cmp
      aria-hidden="true"
      size={size}
      {...base}
      {...rest}
      style={{ verticalAlign: '-0.18em', flexShrink: 0, ...(base.style || {}), ...style }}
    />
  );
}

const RE = new RegExp(`(${Object.keys(GLYPHS).join('|')})\\uFE0F?`, 'g');

/** Turns any legacy emoji in a string into inline <Icon/>s. Plain strings pass through unchanged. */
export function withIcons(text) {
  if (typeof text !== 'string') return text;
  const parts = [];
  let last = 0;
  let i = 0;
  let m;
  RE.lastIndex = 0;
  while ((m = RE.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    parts.push(<Icon key={i++} name={GLYPHS[m[1]]} />);
    last = RE.lastIndex;
  }
  if (last === 0) return text;
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}
