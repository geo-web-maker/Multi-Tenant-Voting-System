import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import BallotBox from './BallotBox';
import { useBlueprint, useDefault, restoreTemplate } from '../test/template';
import { castBallot } from '../voteOutcome';

vi.mock('../api', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../voteOutcome', () => ({
  castBallot: vi.fn(async () => ({ kind: 'success' })),
  checkVoteStatus: vi.fn(async () => true),
}));

const CANDS = [
  { _id: 'a', name: 'Amina Okello', position: 'Chairperson', image_url: '' },
  { _id: 'b', name: 'Brian Kato', position: 'Chairperson', image_url: 'https://example.com/b.jpg' },
  { _id: 'c', name: 'Cate Nabirye', position: 'Treasurer', image_url: '' },
];
const props = (extra) => ({ studentId: 's1', onVoteSuccess: vi.fn(), propCandidates: CANDS, orgName: 'Test Society', ...extra });
const row = (name) => screen.getByRole('button', { name: new RegExp(name) });

beforeEach(() => { sessionStorage.clear(); localStorage.clear(); castBallot.mockClear(); });
afterEach(restoreTemplate);

describe('BallotBox template seam (BP-T4)', () => {
  it('default render has no bp- class, no data-template, no dock', () => {
    useDefault();
    const { container } = render(<BallotBox {...props()} />);
    expect(document.documentElement.dataset.template).toBeUndefined();
    expect(container.querySelector('[class*="bp-"]')).toBeNull();
    expect(container.querySelectorAll('h3.position-header')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /review & submit \(0\)/i })).toBeDisabled();
  });

  it('blueprint: position headings keep the print class `position-header` and gain the pill class', async () => {
    await useBlueprint();
    const { container } = render(<BallotBox {...props()} />);
    const heads = [...container.querySelectorAll('h3.position-header.bp-pos')];
    expect(heads.map((h) => h.textContent)).toEqual(['Chairperson', 'Treasurer']);
  });

  it('blueprint: tap toggles select / deselect, and one pick per position', async () => {
    await useBlueprint();
    render(<BallotBox {...props()} />);
    fireEvent.click(row('Amina'));
    expect(row('Amina')).toHaveAttribute('aria-pressed', 'true');
    expect(row('Amina')).toHaveClass('bp-on');
    fireEvent.click(row('Brian'));
    expect(row('Amina')).toHaveAttribute('aria-pressed', 'false');
    expect(row('Brian')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(row('Brian'));
    expect(row('Brian')).toHaveAttribute('aria-pressed', 'false');
  });

  it('blueprint: keyboard (Enter / Space) toggles a row; the tick is not announced', async () => {
    await useBlueprint();
    const { container } = render(<BallotBox {...props()} />);
    fireEvent.keyDown(row('Cate'), { key: 'Enter' });
    expect(row('Cate')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.keyDown(row('Cate'), { key: ' ' });
    expect(row('Cate')).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelector('.bp-tick')).toHaveAttribute('aria-hidden', 'true');
  });

  it('blueprint: dock label stays REVIEW & SUBMIT (n); disabled while empty', async () => {
    await useBlueprint();
    const { container } = render(<BallotBox {...props()} />);
    expect(container.querySelector('.bp-dock')).not.toBeNull();
    expect(screen.getByRole('button', { name: 'REVIEW & SUBMIT (0)' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear All' })).toBeDisabled();
    fireEvent.click(row('Amina'));
    fireEvent.click(row('Cate'));
    expect(screen.getByRole('button', { name: 'REVIEW & SUBMIT (2)' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Clear All' })).toBeEnabled();
  });

  it('blueprint: isPreview hides the dock and shows the sample banner', async () => {
    await useBlueprint();
    const { container } = render(<BallotBox {...props({ isPreview: true })} />);
    expect(container.querySelector('.bp-dock')).toBeNull();
    expect(screen.getByText(/SAMPLE BALLOT GUIDE - VOTING DISABLED/)).toBeInTheDocument();
  });

  it('blueprint: Clear All asks first; Keep My Votes keeps them, Yes, Clear All clears', async () => {
    await useBlueprint();
    render(<BallotBox {...props()} />);
    fireEvent.click(row('Amina'));
    fireEvent.click(screen.getByRole('button', { name: 'Clear All' }));
    expect(screen.getByText('Reset Entire Ballot?')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Keep My Votes' }));
    expect(row('Amina')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Clear All' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, Clear All' }));
    expect(row('Amina')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText('Reset Entire Ballot?')).toBeNull();
  });

  it('blueprint: review countdown gates the cast button; data-track kept; cast goes through', async () => {
    await useBlueprint();
    vi.useFakeTimers();
    try {
      const p = props();
      render(<BallotBox {...p} />);
      fireEvent.click(row('Amina'));
      fireEvent.click(screen.getByRole('button', { name: /REVIEW & SUBMIT \(1\)/ }));
      expect(screen.getByText('Review Your Ballot')).toBeInTheDocument();
      const cast = screen.getByRole('button', { name: /Wait \(3s\)/ });
      expect(cast).toBeDisabled();
      expect(cast).toHaveAttribute('data-track', 'ballot-submit');
      for (let i = 0; i < 3; i += 1) await act(async () => { vi.advanceTimersByTime(1000); });
      const ready = screen.getByRole('button', { name: 'Confirm & Cast Vote' });
      expect(ready).toBeEnabled();
      await act(async () => { fireEvent.click(ready); });
      expect(castBallot).toHaveBeenCalledTimes(1);
      expect(castBallot.mock.calls[0][2]).toEqual(['a']);
      expect(p.onVoteSuccess).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  it('blueprint: avatar shows initials without a photo, the photo when there is one', async () => {
    await useBlueprint();
    const { container } = render(<BallotBox {...props()} />);
    const avs = container.querySelectorAll('.bp-av');
    expect(avs).toHaveLength(3);
    expect(avs[0].textContent).toBe('AO');
    expect(avs[0].querySelector('img')).toBeNull();
    expect(avs[1].querySelector('img')).not.toBeNull();
    expect(avs[2].textContent).toBe('CN');
  });

  it('blueprint: step bar is decorative, 2 of 3 filled', async () => {
    await useBlueprint();
    const { container } = render(<BallotBox {...props()} />);
    const bar = container.querySelector('.bp-steps');
    expect(bar).toHaveAttribute('aria-hidden', 'true');
    expect(bar.querySelectorAll('i')).toHaveLength(3);
    expect(bar.querySelectorAll('i.bp-on')).toHaveLength(2);
  });

  it('blueprint: dock publishes --bottom-bar-height and clears it on unmount', async () => {
    await useBlueprint();
    const spy = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ height: 88, width: 300, top: 0, left: 0, right: 300, bottom: 88 });
    try {
      const { unmount } = render(<BallotBox {...props()} />);
      expect(document.documentElement.style.getPropertyValue('--bottom-bar-height')).toBe('88px');
      unmount();
      expect(document.documentElement.style.getPropertyValue('--bottom-bar-height')).toBe('');
    } finally { spy.mockRestore(); }
  });
});
