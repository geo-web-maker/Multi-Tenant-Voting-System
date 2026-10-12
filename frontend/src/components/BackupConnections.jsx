import React from 'react';
import { BackupButton, BackupCard, BackupPill, GuardRows } from './BackupUI';
import { bytesText, muted, safeTime } from './BackupUtils';

export default function BackupConnections({ data, summary, onTest, viewAs }) {
  const probes = data?.connections || summary?.connections || [];
  const guards = data?.guards || summary?.guards || [];
  const live = probes.find((p) => p.id === 'live_mongo');
  const tempDbs = live?.detail?.temporary_databases;
  const ownerless = summary?.ownerless_preflight;
  const orphanRows = Object.entries(ownerless?.counts || {}).filter(([, count]) => Number(count) > 0);
  return <div className="perf-grid">
    {ownerless ? <BackupCard title="Backup ownership preflight" note="Newly covered tenant collections must not contain records without an owner before cutover.">
      <BackupPill state={ownerless.safe ? 'passed' : 'failed'}>{ownerless.safe ? 'Passed' : 'Action required'}</BackupPill>
      {orphanRows.length ? <div style={{ display: 'grid', gap: 6, marginTop: 10 }}>{orphanRows.map(([name, count]) => <div key={name} className="perf-controls" style={{ justifyContent: 'space-between' }}><span>{name}</span><strong>{count} ownerless</strong></div>)}</div> : <p style={muted}>No ownerless records were found in the newly covered collections.</p>}
    </BackupCard> : null}
    {tempDbs?.length ? <BackupCard title="Temporary databases on the live cluster">
      <p style={{ ...muted, color: 'var(--warning)' }}>The live cluster contains {tempDbs.join(' and ')}. Drop these in Atlas. This tab does not delete databases.</p>
    </BackupCard> : tempDbs === null || tempDbs === undefined ? <BackupCard title="Temporary database check">
      <p style={muted}>Atlas may not allow listing databases. Confirm manually that the live cluster does not contain databases named mirror or restore_test after cutover.</p>
    </BackupCard> : null}
    <div className="perf-pair">
      {probes.map((p) => <BackupCard key={p.id} title={p.label}>
        <div className="perf-controls" style={{ justifyContent: 'space-between' }}>
          <BackupPill state={p.status}>{p.status || 'Not checked'}</BackupPill>
          <strong>{p.latency_ms == null ? '—' : `${p.latency_ms} ms`}</strong>
        </div>
        <p style={{ ...muted, overflowWrap: 'anywhere' }}>{typeof p.detail === 'string' ? p.detail : JSON.stringify(p.detail || {})}</p>
        {p.detail && typeof p.detail === 'object' ? <div className="perf-tiles" style={{ marginTop: 10 }}>
          {p.detail.database ? <div className="perf-tile"><span style={muted}>Database</span><strong>{p.detail.database}</strong></div> : null}
          {p.detail.server_version ? <div className="perf-tile"><span style={muted}>MongoDB version</span><strong>{p.detail.server_version}</strong></div> : null}
          {p.detail.collections != null ? <div className="perf-tile"><span style={muted}>Collections</span><strong>{p.detail.collections}</strong></div> : null}
          {p.detail.size_bytes != null ? <div className="perf-tile"><span style={muted}>Size</span><strong>{bytesText(p.detail.size_bytes)} / {bytesText(p.detail.limit_bytes)}</strong></div> : null}
          {p.detail.last_sync_at ? <div className="perf-tile"><span style={muted}>Last mirror sync</span><strong>{safeTime(p.detail.last_sync_at)}</strong></div> : null}
        </div> : null}
      </BackupCard>)}
    </div>
    <BackupCard title="Safety guard checks"><GuardRows guards={guards} /></BackupCard>
    <BackupCard title="Connection actions" note="A manual probe bypasses the 15-second cache and writes one monitoring sample.">
      <BackupButton primary disabled={viewAs} onClick={onTest}>Test connections now</BackupButton>
      {viewAs ? <p style={muted}>Disabled in a read-only view-as session.</p> : null}
    </BackupCard>
  </div>;
}
