import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api, { getErrorMessage } from '../api';
import { useToast, useConfirm } from './UIFeedback';
import RevealGroup from './RevealGroup';
import { LoadingBlock } from './Spinner.jsx';
import usePolling from '../hooks/usePolling';
import { TimelineChart, HourBars, BarRows } from './UsageCharts';
import { ApplyFunnelPanel, VotingFunnelPanel, FrictionDetail, NetworkPerformance, ChannelsPanel } from './FunnelPanels';
import { fmtZoned, parseUtc, DEFAULT_TZ } from '../tz';

const HEATMAP_PAGES = ['voter_identity', 'results', 'apply'];
const FRAME_WIDTHS = [390, 820, 1280];
const pct = (v) => `${((v || 0) * 100).toFixed(1)}%`;
const ms = (v) => (v === null || v === undefined ? 'n/a' : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${v} ms`);

// Time range covered by the timeline points, to decide which election markers are in view.
function pointsRange(points) {
  if (!points.length) return null;
  const at = (t) => new Date(t.length === 10 ? `${t}T00:00:00Z` : t).getTime();
  const start = at(points[0].t);
  const step = points.length > 1 ? at(points[1].t) - start : 3600000;
  return { start, end: at(points[points.length - 1].t) + step };
}

// Hours of the day shifted from UTC into the election time zone.
function shiftHours(values, tz) {
  const now = new Date();
  const local = new Date(now.toLocaleString('en-US', { timeZone: tz }));
  const utc = new Date(now.toLocaleString('en-US', { timeZone: 'UTC' }));
  const off = Math.round((local - utc) / 3600000);
  const out = new Array(24).fill(0);
  values.forEach((v, h) => { out[(((h + off) % 24) + 24) % 24] += v; });
  return out;
}

export default function AnalyticsPanel({ organizations = [] }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [days, setDays] = useState(7);
  const [seg, setSeg] = useState('public');
  const [device, setDevice] = useState('all');
  const [apiAud, setApiAud] = useState('voter'); // API table: voter-facing | staff | all
  const [auto, setAuto] = useState(false);
  const [compare, setCompare] = useState(false);
  const [selected, setSelected] = useState([]);
  const [data, setData] = useState(null);
  const [cmp, setCmp] = useState(null);
  const [schedule, setSchedule] = useState(null);
  const [loading, setLoading] = useState(true);
  const [frame, setFrame] = useState(null); // { page, width }

  const load = useCallback(async () => {
    try {
      const params = { days, seg, device };
      if (compare) {
        if (selected.length) {
          const r = await api.get('/superadmin/analytics/compare', { params: { ...params, orgs: selected.join(',') } });
          setCmp(r.data);
        } else setCmp(null);
      } else {
        const r = await api.get('/superadmin/analytics/summary', { params });
        setData(r.data);
      }
    } catch (e) {
      toast(getErrorMessage(e, 'Unable to load Site Usage.'), { kind: 'error' });
    } finally { setLoading(false); }
  }, [days, seg, device, compare, selected, toast]);

  useEffect(() => { setLoading(true); load(); }, [load]);
  useEffect(() => { api.get('/election-schedule').then((r) => setSchedule(r.data)).catch(() => {}); }, []);
  usePolling(load, 30000, auto);

  const apiRows = (data?.api || []).filter((a) => apiAud === 'all' || a.audience === apiAud);
  const tz = schedule?.timezone || DEFAULT_TZ;
  const points = data?.timeline?.points || [];
  const markers = useMemo(() => {
    const v = schedule?.phases?.voting;
    if (!v) return [];
    return [['Voting opens', v.start], ['Voting closes', v.end]].filter(([, t]) => t)
      .map(([label, t]) => ({ label, t: parseUtc(t)?.getTime() ?? NaN, iso: t, strong: true }));
  }, [schedule]);
  const range = pointsRange(points);
  const visibleMarkers = range ? markers.filter((m) => m.t >= range.start && m.t <= range.end) : [];

  const clear = async () => {
    if (!(await confirm('Clear all Site Usage analytics for this organisation? This cannot be undone.', { danger: true, confirmText: 'Clear analytics' }))) return;
    try {
      await api.delete('/superadmin/analytics', { data: { confirm: true } });
      toast('Site Usage analytics cleared.', { kind: 'success' });
      load();
    } catch (e) { toast(getErrorMessage(e, 'Unable to clear analytics.'), { kind: 'error' }); }
  };
  const toggleOrg = (slug) => setSelected((cur) => (cur.includes(slug) ? cur.filter((s) => s !== slug) : cur.length >= 4 ? cur : [...cur, slug]));

  if (loading && !data && !cmp) return <LoadingBlock text="Loading Site Usage…" />;
  const t = data?.totals || {};

  return (
    <RevealGroup>
      <div style={{ display: 'grid', gap: 16 }}>
        <div style={panel} className="card-pad">
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <select aria-label="Date range" value={days} onChange={(e) => setDays(Number(e.target.value))} style={inputStyle}>
              {[1, 7, 30, 90].map((d) => <option key={d} value={d}>{d === 1 ? 'Last 24 hours' : `Last ${d} days`}</option>)}
            </select>
            <div role="group" aria-label="Audience" style={{ display: 'flex', flex: '1 1 200px', gap: 4 }}>
              {[['public', 'Public'], ['staff', 'Staff'], ['all', 'All']].map(([v, l]) => (
                <button key={v} type="button" aria-pressed={seg === v} onClick={() => setSeg(v)} style={seg === v ? segOn : segOff}>{l}</button>
              ))}
            </div>
            <select aria-label="Device" value={device} onChange={(e) => setDevice(e.target.value)} style={inputStyle}>
              <option value="all">All devices</option><option value="mobile">Mobile</option>
              <option value="tablet">Tablet</option><option value="desktop">Desktop</option>
            </select>
            <button type="button" style={btn} onClick={() => { setLoading(true); load(); }}>Refresh</button>
            <label style={check}><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-refresh (30 s)</label>
            <label style={check}><input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} /> Compare organisations</label>
          </div>
          {compare && (
            <div style={{ marginTop: 12 }}>
              <p style={muted}>Select up to four organisations. The filters above apply to all of them.</p>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}>
                {organizations.map((o) => (
                  <label key={o.slug} style={{ ...check, ...chip, opacity: !selected.includes(o.slug) && selected.length >= 4 ? 0.5 : 1 }}>
                    <input type="checkbox" checked={selected.includes(o.slug)} onChange={() => toggleOrg(o.slug)} /> {o.name || o.slug}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>

        {compare ? (
          !cmp ? <div style={panel} className="card-pad"><p style={muted}>Select at least one organisation to compare.</p></div> : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
              {cmp.map((o) => (
                <div key={o.slug} style={panel} className="card-pad">
                  <h3 style={h3}>{organizations.find((x) => x.slug === o.slug)?.name || o.slug}</h3>
                  {!o.found ? <p style={muted}>This organisation was not found.</p> : (
                    <>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
                        {[['Views', o.totals.views], ['Sessions', o.totals.sessions], ['Peak concurrency', o.peak_concurrency],
                          ['API error rate', pct(o.api_error_rate)], ['Load p95', ms(o.load_p95)], ['Bounce', pct(o.totals.bounce)]].map(([k, v]) => (
                          <div key={k}><div style={muted}>{k}</div><strong>{v}</strong></div>
                        ))}
                      </div>
                      <div style={{ marginTop: 12 }}><TimelineChart points={o.timeline} bucket="day" /></div>
                      <h4 style={h4}>Devices</h4><BarRows items={o.devices} />
                      <h4 style={h4}>Top pages</h4><BarRows items={o.top_pages} />
                    </>
                  )}
                </div>
              ))}
            </div>
          )
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
              {[['Page views', t.views || 0], ['Sessions', t.sessions || 0], ['Pages per session', t.pages_per_session || 0],
                ['Bounce rate', pct(t.bounce)], ['Average session', `${t.average_session_seconds || 0} s`],
                ['Live now (approximate)', t.live_now || 0], ['Peak concurrency', t.peak_concurrency || 0]].map(([k, v]) => (
                <div key={k} style={panel} className="card-pad"><div style={muted}>{k}</div><strong style={{ fontSize: 20 }}>{v}</strong></div>
              ))}
            </div>

            <div style={panel} className="card-pad">
              <h3 style={h3}>Views and sessions</h3>
              <TimelineChart points={points} markers={markers} bucket={data?.timeline?.bucket} />
              <div style={legend}>
                <span><i style={{ ...dot, background: 'var(--brand-primary)' }} /> Views</span>
                <span><i style={{ ...dot, background: 'var(--brand-accent)' }} /> Sessions</span>
                {points.some((p) => p.votes > 0) && <span><i style={{ ...dot, background: 'var(--success, #2e9e5b)' }} /> Votes cast</span>}
                {visibleMarkers.map((m) => (
                  <span key={m.label}><i style={{ ...dot, background: 'var(--danger)' }} /> {m.label} {fmtZoned(m.iso, tz)}</span>
                ))}
              </div>
              <p style={muted}>Chart labels are in UTC. Marker times are shown in {tz}.</p>
            </div>

            <ApplyFunnelPanel funnel={data?.funnels?.apply} />
            <VotingFunnelPanel funnel={data?.funnels?.voting} />

            <div style={panel} className="card-pad">
              <h3 style={h3}>Activity by hour of day</h3>
              <HourBars values={shiftHours(data?.hour_of_day || new Array(24).fill(0), tz)} zoneLabel={tz} />
              <p style={muted}>Hours are shown in {tz}.</p>
            </div>

            <div style={grid}>
              <Card title="Top pages"><BarRows items={data?.top_pages} sub={(x) => `Sessions ${x.sessions_reached} · entries ${x.entries} · exits ${x.exits}`} /></Card>
              <Card title="Devices"><BarRows items={data?.devices} /></Card>
              <Card title="Browsers"><BarRows items={data?.browsers} /></Card>
              <Card title="Operating systems"><BarRows items={data?.os} /></Card>
              <Card title="Entry sources"><BarRows items={data?.entry_sources} sub={(x) => `Bounce rate ${pct(x.bounce)}`} /></Card>
              <Card title="Entry page and source"><BarRows items={data?.entries} sub={(x) => `Bounce rate ${pct(x.bounce)}`} /></Card>
              <Card title="Movement between pages"><BarRows items={data?.transitions} /></Card>
            </div>

            <div style={panel} className="card-pad">
              <h3 style={h3}>Hotspots</h3>
              <p style={muted}>Most-clicked named elements, by page.</p>
              {Object.entries((data?.elements || []).reduce((a, e) => { (a[e.page] = a[e.page] || []).push(e); return a; }, {})).map(([page, items]) => (
                <div key={page} style={{ marginTop: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <h4 style={{ ...h4, margin: 0, overflowWrap: 'anywhere' }}>{page}</h4>
                    {HEATMAP_PAGES.includes(page) && <button type="button" style={btn} onClick={() => setFrame({ page, width: 390 })}>Heatmap</button>}
                  </div>
                  <BarRows items={items.slice(0, 8)} />
                </div>
              ))}
              {!data?.elements?.length && <p style={muted}>No clicks have been recorded for this period.</p>}
              <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {HEATMAP_PAGES.filter((p) => !data?.elements?.some((e) => e.page === p)).map((p) => (
                  <button key={p} type="button" style={btn} onClick={() => setFrame({ page: p, width: 390 })}>Heatmap: {p}</button>
                ))}
              </div>
            </div>

            <ChannelsPanel channels={data?.channels} />

            <div style={panel} className="card-pad">
              <h3 style={h3}>Friction</h3>
              <BarRows items={[
                { label: 'Dead clicks', value: data?.quality?.dead_clicks || 0 },
                { label: 'Rage clicks', value: data?.quality?.rage_clicks || 0 },
                { label: 'Front-end errors', value: data?.quality?.errors || 0 },
                { label: 'Network failures', value: data?.quality?.network_failures || 0 },
              ]} />
              <h4 style={h4}>Error classes</h4>
              <BarRows items={data?.error_classes} empty="No errors have been recorded for this period." />
            </div>

            <FrictionDetail friction={data?.friction} />

            <div style={panel} className="card-pad">
              <h3 style={h3}>Reliability and performance</h3>
              <p style={{ margin: '0 0 10px', fontSize: 14 }}>
                Suspected cold starts: {pct(data?.cold_starts?.pct)} of measured sessions ({data?.cold_starts?.suspected || 0} of {data?.cold_starts?.sessions || 0}).
              </p>
              <h4 style={h4}>API outcomes by route</h4>
              <div role="group" aria-label="API audience" style={{ display: 'flex', gap: 4, marginBottom: 8, maxWidth: 420 }}>
                {[['voter', 'Voter-facing'], ['staff', 'Staff'], ['all', 'All']].map(([v, l]) => (
                  <button key={v} type="button" aria-pressed={apiAud === v} onClick={() => setApiAud(v)} style={apiAud === v ? segOn : segOff}>{l}</button>
                ))}
              </div>
              {apiRows.length ? (
                <div className="table-scroll">
                  <table style={table}>
                    <thead><tr>{['Route', 'Requests', '401', '429', 'Other 4xx', '5xx', 'p50', 'p95'].map((c) => <th key={c} style={th}>{c}</th>)}</tr></thead>
                    <tbody>{apiRows.map((a) => (
                      <tr key={a.route}>
                        <td style={{ ...td, overflowWrap: 'anywhere' }}>{a.route}</td><td style={td}>{a.requests}</td><td style={td}>{a.e401}</td>
                        <td style={td}>{a.e429}</td><td style={td}>{a.e4}</td><td style={td}>{a.e5}</td><td style={td}>{ms(a.p50)}</td><td style={td}>{ms(a.p95)}</td>
                      </tr>))}
                    </tbody>
                  </table>
                </div>
              ) : <p style={muted}>No API outcomes have been recorded for this period.</p>}
              <h4 style={h4}>Page load and first response, by entry page and device</h4>
              <BarRows items={(data?.perf || []).map((p) => ({ label: `${p.page} · ${p.device}`, value: p.sessions, p }))}
                sub={(x) => `Load p50 ${ms(x.p.load_p50)}, p95 ${ms(x.p.load_p95)} · first API p50 ${ms(x.p.first_api_p50)}, p95 ${ms(x.p.first_api_p95)} · cold ${pct(x.p.cold_pct)}`} />
              <NetworkPerformance rows={data?.network_perf} />
              <h4 style={h4}>Network quality</h4>
              <BarRows items={data?.network} format={(v) => v} sub={(x) => `${pct(x.share)} of sessions`} />
              <p style={{ ...muted, marginTop: 12 }}>
                Peak concurrency: {t.peak_concurrency || 0}{t.peak_concurrency_time ? ` at ${fmtZoned(t.peak_concurrency_time, tz)}` : ''}.
                {' '}Use about 1.5 × this value ({Math.ceil((t.peak_concurrency || 0) * 1.5)}) as the number of users in <code>backend/loadtest/locustfile.py</code>.
              </p>
            </div>

            <div style={panel} className="card-pad">
              <h3 style={h3}>Danger zone</h3>
              <p style={muted}>Clears all Site Usage data for the active organisation. Voting data is not affected.</p>
              <button type="button" style={dangerBtn} onClick={clear}>Clear analytics</button>
              <p style={{ ...muted, marginTop: 10 }}>Last saved to the database: {data?.meta?.last_flush_at ? fmtZoned(data.meta.last_flush_at, tz) : 'not yet'}. Dropped batches: {data?.meta?.dropped_over_capacity ?? 0}.</p>
            </div>
          </>
        )}
      </div>

      {frame && (
        <div style={modalOverlay} onClick={() => setFrame(null)}>
          <div style={modalContent} onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Page heatmap">
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
              <strong style={{ flex: '1 1 100%' }}>Heatmap: {frame.page}</strong>
              {FRAME_WIDTHS.map((w) => (
                <button key={w} type="button" aria-pressed={frame.width === w} style={frame.width === w ? segOn : segOff} onClick={() => setFrame({ ...frame, width: w })}>{w} px</button>
              ))}
              <button type="button" style={btn} onClick={() => setFrame(null)}>Close</button>
            </div>
            <p style={muted}>Vertical positions may drift slightly when page length changes.</p>
            <div style={{ overflow: 'auto', maxWidth: '100%', marginTop: 10, border: '1px solid var(--border-color)', borderRadius: 8 }}>
              <iframe key={`${frame.page}-${frame.width}`} title={`Heatmap of ${frame.page}`} src={`${window.location.origin}/?heatmap=${frame.page}`}
                style={{ width: frame.width, maxWidth: 'none', height: '60vh', border: 0, display: 'block' }} />
            </div>
          </div>
        </div>
      )}
    </RevealGroup>
  );
}

function Card({ title, children }) {
  return <div style={panel} className="card-pad"><h3 style={h3}>{title}</h3>{children}</div>;
}

const panel = { border: '1px solid var(--border-color)', borderRadius: 12, padding: 16, background: 'var(--card-bg)', minWidth: 0 };
const grid = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 };
const muted = { color: 'var(--text-muted)', fontSize: 13, margin: 0 };
const h3 = { margin: '0 0 10px', fontSize: 15 };
const h4 = { margin: '14px 0 6px', fontSize: 13, color: 'var(--text-muted)' };
const inputStyle = { minHeight: 44, padding: '8px 10px', border: '1px solid var(--border-color)', borderRadius: 8, background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 13, flex: '1 1 140px' };
const btn = { minHeight: 44, padding: '0 16px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--brand-primary)', color: 'var(--card-bg)', fontWeight: 700, fontSize: 13, cursor: 'pointer' };
const dangerBtn = { ...btn, background: 'var(--danger)' };
const segOff = { flex: 1, minHeight: 44, padding: '0 12px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontWeight: 700, fontSize: 13, cursor: 'pointer' };
const segOn = { ...segOff, background: 'var(--brand-primary)', color: 'var(--card-bg)', borderColor: 'var(--brand-primary)' };
const check = { display: 'flex', alignItems: 'center', gap: 8, minHeight: 44, fontSize: 13 };
const chip = { padding: '0 12px', border: '1px solid var(--border-color)', borderRadius: 8, background: 'var(--surface-2)' };
const legend = { display: 'flex', flexWrap: 'wrap', gap: '6px 16px', fontSize: 12, margin: '8px 0' };
const dot = { display: 'inline-block', width: 10, height: 10, borderRadius: '50%', marginRight: 6 };
const table = { width: '100%', borderCollapse: 'collapse', fontSize: 13 };
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', whiteSpace: 'nowrap' };
const td = { padding: '6px 8px', borderBottom: '1px solid var(--border-color)' };
const modalOverlay = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.85)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 };
const modalContent = { backgroundColor: 'var(--card-bg)', padding: 20, borderRadius: 16, width: '90%', maxWidth: 1000, maxHeight: '85vh', overflowY: 'auto' };
