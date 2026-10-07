import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import BootSplash from './BootSplash';
import { PublicWrap } from './primitives';

const props = { orgName: 'Kyambogo Engineering Society', logoUrl: '', exiting: false, text: 'The server is waking up.', label: 'STARTING SERVER', dot: 'var(--warning, #eab308)' };

describe('blueprint BootSplash', () => {
  it('keeps the stage copy, label (role=status) and dot colour; the ring becomes the initials stamp', () => {
    const { container } = render(<BootSplash {...props} />);
    expect(screen.getByRole('heading', { name: 'Kyambogo Engineering Society' })).toBeInTheDocument();
    expect(screen.getByText('The server is waking up.')).toHaveAttribute('aria-live', 'polite');
    expect(screen.getByRole('status')).toHaveTextContent('STARTING SERVER');
    expect(container.querySelector('.bp-dot')).toHaveStyle({ background: 'var(--warning, #eab308)' });
    expect(container.querySelector('.bp-logo')).toHaveTextContent('KES');
  });
  it('uses the logo image inside the stamp when there is one', () => {
    const { container } = render(<BootSplash {...props} logoUrl="https://x/l.png" />);
    expect(container.querySelector('.bp-logo img')).toHaveAttribute('src', 'https://x/l.png');
  });
  it('exit fade matches the default hand-off', () => {
    const { container } = render(<BootSplash {...props} exiting />);
    expect(container.firstChild).toHaveStyle({ opacity: '0', pointerEvents: 'none' });
  });
  it('falls back to "Election Portal" without an org name', () => {
    render(<BootSplash {...props} orgName="" />);
    expect(screen.getByRole('heading', { name: 'Election Portal' })).toBeInTheDocument();
  });
});

describe('PublicWrap', () => {
  it('520 column by default, wide variant for results', () => {
    const { container, rerender } = render(<PublicWrap><p>x</p></PublicWrap>);
    expect(container.firstChild).toHaveClass('bp-wrap');
    expect(container.firstChild).not.toHaveClass('bp-wide');
    rerender(<PublicWrap wide><p>x</p></PublicWrap>);
    expect(container.firstChild).toHaveClass('bp-wide');
  });
});
