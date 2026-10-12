import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { setTemplateImpl } from '../template';
import { ChecklistRows, DetailLines, GuardRows } from './BackupUI';

const fakeBlueprint = {
  cls: { card: 'bp-card-x', alt: 'bp-alt-x', warnBan: 'bp-ban bp-warn' },
  Pill: ({ tone, children }) => <span data-testid="bp-pill" data-tone={tone}>{children}</span>,
};
const ITEMS = [
  { name: 'No election open', ok: false, detail: ['assk', 'kyues'] },
  { name: 'Probes healthy', ok: false, detail: { live_mongo: 'down', migration_target: 'unconfigured', postgres_history: 'ok' } },
  { name: 'Mirror synced', ok: true },
  { name: 'No ownerless records', ok: true, detail: { candidate_lists: 0, certificates: 0 } },
];
afterEach(() => { cleanup(); setTemplateImpl(null); });

describe.each([['standard', null], ['blueprint', fakeBlueprint]])('ChecklistRows in the %s template', (_n, impl) => {
  const setup = (props = {}) => { setTemplateImpl(impl); return render(<ChecklistRows items={ITEMS} {...props} />); };

  it('summarises how many checks pass and lists blocked checks first', () => {
    setup();
    expect(screen.getByRole('status').textContent).toBe('2 of 4 checks passing');
    const names = screen.getAllByRole('listitem').filter((li) => li.className === 'perf-checkrow').map((li) => within(li).getByText(/^(No |Probes|Mirror)/, { selector: 'strong' }).textContent);
    expect(names.slice(0, 2)).toEqual(['No election open', 'Probes healthy']);
  });

  it('states each result in words, exactly once per item', () => {
    setup();
    expect(screen.getAllByText('Blocked')).toHaveLength(2);
    expect(screen.getAllByText('Passed')).toHaveLength(2);
  });

  it('never prints raw JSON: lists become chips, objects become label/value rows', () => {
    const { container } = setup({ captions: { 'No election open': 'Open now' } });
    expect(container.textContent).not.toMatch(/[{}[\]"]/);
    expect(container.querySelectorAll('.perf-chips li')).toHaveLength(2);
    expect(screen.getByText('Open now')).toBeTruthy();
    expect(container.querySelector('dt').textContent).toBe('live mongo');
    expect(container.querySelector('dd[data-status="failed"]').textContent).toBe('Failed');
    expect(screen.getByText('Not configured')).toBeTruthy();   // 'unconfigured' reads as words
  });

  it('marks the icon by state for colour, with the word carried by the pill', () => {
    const { container } = setup();
    expect(container.querySelectorAll('.perf-checkicon[data-ok="false"]')).toHaveLength(2);
    expect(container.querySelectorAll('.perf-checkicon[data-ok="true"]')).toHaveLength(2);
    expect(container.querySelector('.perf-checkicon').getAttribute('aria-hidden')).toBe('true');
  });

  it('shows the empty message and nothing else when there are no checks', () => {
    setTemplateImpl(impl);
    render(<ChecklistRows items={[]} empty="Readiness checks have not run yet." />);
    expect(screen.getByText('Readiness checks have not run yet.')).toBeTruthy();
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('GuardRows keeps its "Failed" wording', () => {
    setTemplateImpl(impl);
    render(<GuardRows guards={[{ name: 'Write guard', ok: false, detail: 'Frozen' }]} />);
    expect(screen.getByText('Failed')).toBeTruthy();
    expect(screen.getByText('Frozen')).toBeTruthy();
  });
});

describe('DetailLines', () => {
  it('renders nothing for empty details', () => {
    for (const d of [null, '', [], {}]) { const { container } = render(<DetailLines detail={d} />); expect(container.innerHTML).toBe(''); cleanup(); }
  });
  it('keeps a plain string as text', () => {
    render(<DetailLines detail="Run the plan first." />);
    expect(screen.getByText('Run the plan first.')).toBeTruthy();
  });
});

describe('both templates are styled', () => {
  const live = readFileSync('src/templates/blueprint/blueprint.css', 'utf8');
  const std = readFileSync('src/index.css', 'utf8');
  const classes = ['perf-checkrow', 'perf-checkicon', 'perf-chips', 'perf-kv', 'perf-tile-label'];
  it('the standard stylesheet defines every checklist class', () => {
    for (const c of classes) expect(std, c).toContain(`.${c}`);
  });
  it('the stylesheet Blueprint actually imports styles tiles and checklists, scoped and without !important', () => {
    for (const c of ['perf-tile', ...classes.slice(0, 4)]) expect(live, c).toContain(`html[data-template="blueprint"] .${c}`);
    const block = live.slice(live.indexOf('===== PANEL KIT'), live.indexOf('html[data-template="blueprint"] .perf-chips li'));
    expect(block).not.toContain('!important');
    expect(block).toContain('var(--bp-ok)');
    expect(block).toContain('var(--bp-no)');
  });
  it('src/templates/blueprint/index.js imports that same file', () => {
    expect(readFileSync('src/templates/blueprint/index.js', 'utf8')).toContain("import './blueprint.css'");
  });
});
