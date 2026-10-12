import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { readFileSync, readdirSync } from 'node:fs';
import { setTemplateImpl } from '../template';
import { BackupCard, BackupPill, tileClass, cardClass } from './BackupUI';

const fakeBlueprint = {
  cls: { card: 'bp-card-x', alt: 'bp-alt-x', warnBan: 'bp-ban bp-warn' },
  Pill: ({ tone, children }) => <span data-testid="bp-pill" data-tone={tone}>{children}</span>,
};

afterEach(() => { cleanup(); setTemplateImpl(null); });

describe('Backups UI follows the active template', () => {
  it('uses the standard classes and pill in the default template', () => {
    render(<BackupCard title="T"><BackupPill state="passed" /></BackupCard>);
    expect(document.querySelector('.perf-card')).toBeTruthy();
    expect(screen.queryByTestId('bp-pill')).toBeNull();
    expect(screen.getByText('Healthy')).toBeTruthy();
    expect(tileClass()).toContain('perf-tile');
  });

  it('uses the Blueprint card, tile surface and Pill when Blueprint is registered', () => {
    setTemplateImpl(fakeBlueprint);
    render(<BackupCard title="T"><BackupPill state="failed" /></BackupCard>);
    expect(document.querySelector('.bp-card-x')).toBeTruthy();
    expect(document.querySelector('.perf-card')).toBeNull();
    expect(screen.getByTestId('bp-pill').dataset.tone).toBe('neg');
    expect(cardClass()).toBe('bp-card-x');
    expect(tileClass()).toBe('perf-tile');        // never bp.cls.alt: that is Blueprint's red error block
  });

  it('never states health by colour alone: the word is always rendered', () => {
    for (const [state, word] of [['warning', 'Warning'], ['failed', 'Failed'], ['running', 'Running'], ['never', 'Not run']]) {
      render(<BackupPill state={state} />);
      expect(screen.getByText(word)).toBeTruthy();
      cleanup();
    }
  });

  it('blueprint.css gives the shared perf controls scoped 48 px rules inside @media screen, without !important', () => {
    const css = readFileSync('src/blueprint.css', 'utf8');
    const start = css.indexOf('BACKUPS / PERFORMANCE TABS');
    expect(start).toBeGreaterThan(css.indexOf('@media screen'));
    expect(start).toBeLessThan(css.indexOf('7. PRINT'));
    const section = css.slice(start, css.indexOf('/* ===== /NEUTRALISERS'));
    expect(section).toMatch(/\.perf-btn[^{]*\{[^}]*min-height: var\(--bp-tap\)/);
    expect(section).toMatch(/\.perf-field[^{]*\{[^}]*min-height: var\(--bp-tap\)/);
    expect(section).not.toContain('!important');
    expect(section).toContain('--bp-ai');
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
