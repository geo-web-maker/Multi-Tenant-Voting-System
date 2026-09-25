import React from 'react';
import api from '../api';

/**
 * Nomination fee list, shown from the Help menu so anyone can check what a
 * position costs before opening the application form (which only shows a
 * position's fee after it's been selected). Public endpoint, same one the
 * application form itself reads application_fee from.
 */
export default function FeeSchedule() {
  const [positions, setPositions] = React.useState(null); // null = loading, [] once loaded
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    api.get('/positions')
      .then(res => setPositions(res.data || []))
      .catch(() => setError(true));
  }, []);

  return (
    <div>
      <h3 style={{ marginTop: 0 }}>Nomination Fees</h3>
      {error && <p style={{ opacity: 0.7 }}>Could not load the fee list right now. Please try again shortly.</p>}
      {!error && positions === null && <p style={{ opacity: 0.7 }}>Loading…</p>}
      {!error && positions !== null && positions.length === 0 && (
        <p style={{ opacity: 0.7 }}>No positions have been set up yet.</p>
      )}
      {!error && positions !== null && positions.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {positions.map(p => {
            const fee = Number(p.application_fee || 0);
            return (
              <div key={p._id} style={row}>
                <span style={{ fontWeight: 600 }}>{p.title}</span>
                <span style={{ fontWeight: 700, whiteSpace: 'nowrap', color: fee > 0 ? 'var(--brand-primary)' : 'var(--text-muted)' }}>
                  {fee > 0 ? `UGX ${fee.toLocaleString('en-UG')}` : 'No fee'}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <p style={{ marginTop: '18px', fontSize: '12px', opacity: 0.7 }}>
        Pay the fee for your position and upload proof of payment when you submit your application.
        Applications are not cleared for voting until Finance confirms your payment.
      </p>
    </div>
  );
}

const row = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  gap: '14px', padding: '10px 14px', borderRadius: '10px',
  border: '1px solid var(--border-color)', background: 'var(--card-bg)',
};
