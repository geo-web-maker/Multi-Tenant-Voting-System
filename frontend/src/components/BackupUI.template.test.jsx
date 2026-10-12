import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { setTemplateImpl } from '../template';
import { BackupCard, BackupPill } from './BackupUI';
import { tileClass, cardClass } from './BackupUtils';

const fakeBlueprint = {
  cls: { card: 'bp-card-x', alt: 'bp-alt-x', warnBan: 'bp-ban bp-warn' },
  Pill: ({ tone, children }) => <span data-testid="bp-pill" data-tone={tone}>{children}</span>,
};

afterEach(() => { cleanup(); setTemplateImpl(null); });

describe('Backups UI follows the active template', () => {
  it('uses the standard classes and pill in the default template', () => {
    setTemplateImpl(null);
    render(<BackupCard title="T"><BackupPill state="passed" /></BackupCard>);
    expect(document.querySelector('.perf-card')).toBeTruthy();
    expect(screen.queryByTestId('bp-pill')).toBeNull();
    expect(screen.getByText('Healthy')).toBeTruthy();
    expect(tileClass()).toContain('perf-tile');
  });

  it('uses the same panel and tile classes in Blueprint, with the Blueprint Pill', () => {
    setTemplateImpl(fakeBlueprint);
    render(<BackupCard title="T"><BackupPill state="failed" /></BackupCard>);
    // One card for both templates: a second bp-card would nest an accent top border inside the console shell.
    expect(document.querySelector('.perf-card')).toBeTruthy();
    expect(document.querySelector('.bp-card-x')).toBeNull();
    expect(screen.getByTestId('bp-pill').dataset.tone).toBe('neg');
    expect(cardClass()).toBe('perf-card card-pad');
    expect(tileClass()).toBe('perf-card card-pad perf-tile');
  });

  it('never states health by colour alone: the word is always rendered', () => {
    for (const [state, word] of [['warning', 'Warning'], ['failed', 'Failed'], ['running', 'Running'], ['never', 'Not run']]) {
      render(<BackupPill state={state} />);
      expect(screen.getByText(word)).toBeTruthy();
      cleanup();
    }
  });

  it('the live blueprint.css carries one scoped PANEL KIT block, and no stale second copy exists', () => {
    const css = readFileSync('src/templates/blueprint/blueprint.css', 'utf8');
    const start = css.indexOf('===== PANEL KIT');
    const end = css.indexOf('===== /PANEL KIT');
    expect(start).toBeGreaterThan(css.indexOf('@media screen'));
    expect(end).toBeGreaterThan(start);
    expect(start).toBeLessThan(css.indexOf('===== NEUTRALISERS'));
    const section = css.slice(start, end);
    expect(section).toMatch(/\.perf-btn[^{]*\{[^}]*min-height: var\(--bp-tap\)/);
    expect(section).toMatch(/\.perf-field[^{]*\{[^}]*min-height: var\(--bp-tap\)/);
    expect(section).not.toContain('!important');
    expect(section).toContain('--bp-ai');
    // src/blueprint.css used to be an unimported copy that tests read while the app loaded another file.
    expect(existsSync('src/blueprint.css')).toBe(false);
  });

  it('no Backup component hard-codes the default card class or Blueprint bp- class names', () => {
    const dir = 'src/components';
    const files = readdirSync(dir).filter((f) => /^Backup.*\.jsx$/.test(f) && !/test/.test(f));
    for (const f of files) {
      const src = readFileSync(`${dir}/${f}`, 'utf8');
      expect(src, f).not.toMatch(/className=["'`][^"'`]*\bbp-/);
      if (f !== 'BackupUI.jsx') expect(src, f).not.toMatch(/className="perf-card/);
    }
  });
});
