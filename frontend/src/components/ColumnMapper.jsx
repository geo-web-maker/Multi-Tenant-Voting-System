import React from 'react';

/**
 * "Match columns" step of a voter import. The server has already read the file (POST
 * /admin/import-voters/inspect) and guessed which column is which; this lets the admin correct the
 * guess, pick the sheet and say which row holds the headings, and shows how the first rows will be
 * read before anything is compared with the live roster.
 *
 * `mapping` is { field: ['3', '4'] } (select values, '' = none); see ../columnMapping.js for the helpers
 * that turn it into what the server expects and say whether Continue is allowed.
 */

const colLetter = i => {
  let n = i, s = '';
  do { s = String.fromCharCode(65 + (n % 26)) + s; n = Math.floor(n / 26) - 1; } while (n >= 0);
  return s;
};
const colLabel = (i, heading) => `${colLetter(i)}: ${heading || '(no heading)'}`;

export default function ColumnMapper({ data, mapping, onMapping, onHeaderRow, onSheet, busy }) {
  const usedBy = {};
  Object.entries(mapping).forEach(([k, vals]) => vals.forEach(v => { if (v !== '') usedBy[v] = k; }));
  const labelOf = key => data.targets.find(t => t.key === key)?.label || key;

  const setCol = (key, n, val) => {
    const cur = [...(mapping[key] || [''])];
    cur[n] = val;
    onMapping({ ...mapping, [key]: cur });
  };
  const addCol = key => onMapping({ ...mapping, [key]: [...(mapping[key] || ['']), ''] });
  const dropCol = (key, n) => onMapping({ ...mapping, [key]: (mapping[key] || []).filter((_, i) => i !== n) });

  const mappedTargets = data.targets.filter(t => (mapping[t.key] || []).some(v => v !== ''));
  const readCell = (row, key) => (mapping[key] || []).filter(v => v !== '').map(v => row.cells[Number(v)] || '').filter(Boolean).join(' ');
  const maxHeaderRow = data.raw_preview.length;

  return (
    <div style={{ opacity: busy ? 0.6 : 1 }}>
      <p style={{ margin: '0 0 12px', fontSize: 12, opacity: 0.7 }}>
        Tell us which column of your file holds each detail. Registration number and full name are required; anything
        set to “not in this file” is left alone. Nothing is saved yet.
      </p>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12, fontSize: 12 }}>
        {data.sheets.length > 1 && (
          <label>Sheet:&nbsp;
            <select style={sel} value={data.sheet} disabled={busy} onChange={e => onSheet(e.target.value)}>
              {data.sheets.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        )}
        <label>Headings are on:&nbsp;
          <select style={sel} value={data.header_row} disabled={busy} onChange={e => onHeaderRow(Number(e.target.value))}>
            {data.raw_preview.map(r => (
              <option key={r.row} value={r.row}>
                Row {r.row}{r.cells.filter(Boolean).length ? ` — ${r.cells.filter(Boolean).slice(0, 3).join(', ')}` : ' — (empty)'}
              </option>
            ))}
          </select>
        </label>
        <span style={{ opacity: 0.6, alignSelf: 'center' }}>{data.data_rows} data row(s) below it</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
        {data.targets.map(t => {
          const vals = (mapping[t.key] || []).length ? mapping[t.key] : [''];
          const missing = t.required && !vals.some(v => v !== '');
          return (
            <div key={t.key} style={{ ...mapRow, borderColor: missing ? 'var(--bp-no, #e74c3c)' : 'var(--border-color)' }}>
              <div style={{ minWidth: 0 }}>
                <b style={{ fontSize: 13 }}>{t.label}{t.required ? ' *' : ''}</b>
                {t.multi && <div style={{ fontSize: 11, opacity: 0.55 }}>
                  {t.key === 'full_name' ? 'Can join several columns, e.g. First name + Surname' : 'Can use several columns, e.g. Phone 1 and Phone 2'}
                </div>}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
                {vals.map((val, n) => (
                  <div key={n} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <select style={{ ...sel, maxWidth: 240 }} value={val} disabled={busy}
                      aria-label={`${t.label} column`}
                      onChange={e => setCol(t.key, n, e.target.value)}>
                      <option value="">— not in this file —</option>
                      {data.headers.map((h, i) => {
                        const taken = usedBy[String(i)] && String(i) !== val;
                        return (
                          <option key={i} value={String(i)} disabled={!!taken}>
                            {colLabel(i, h)}{taken ? ` (used for ${labelOf(usedBy[String(i)])})` : ''}
                          </option>
                        );
                      })}
                    </select>
                    {t.multi && n > 0 && <button type="button" style={linkBtn} onClick={() => dropCol(t.key, n)} aria-label="Remove this column">✕</button>}
                  </div>
                ))}
                {t.multi && vals.length < 3 && vals[vals.length - 1] !== '' && (
                  <button type="button" style={linkBtn} onClick={() => addCol(t.key)}>+ add another column</button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>How the first rows will be read</div>
      <div style={scrollBox}>
        <table style={table}>
          <thead>
            <tr><th style={th}>Row</th>{mappedTargets.map(t => <th key={t.key} style={th}>{t.label}</th>)}</tr>
          </thead>
          <tbody>
            {data.sample.length === 0 && <tr><td style={td} colSpan={mappedTargets.length + 1}>No data rows below the heading row.</td></tr>}
            {data.sample.map(r => (
              <tr key={r.row}><td style={td}>{r.row}</td>{mappedTargets.map(t => <td key={t.key} style={td}>{readCell(r, t.key) || <span style={{ opacity: 0.4 }}>—</span>}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>

      <details style={{ marginTop: 12 }}>
        <summary style={{ fontSize: 12, cursor: 'pointer' }}>Show the top of the file (click a row to use it as the headings)</summary>
        <div style={{ ...scrollBox, maxHeight: 180, marginTop: 6 }}>
          <table style={table}>
            <tbody>
              {data.raw_preview.slice(0, maxHeaderRow).map(r => (
                <tr key={r.row} onClick={() => !busy && onHeaderRow(r.row)}
                  style={{ cursor: 'pointer', background: r.row === data.header_row ? 'color-mix(in srgb, var(--info) 15%, transparent)' : 'transparent' }}>
                  <td style={{ ...td, opacity: 0.6 }}>{r.row}</td>
                  {r.cells.map((c, i) => <td key={i} style={{ ...td, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

const sel = { padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border-color)', background: 'var(--bg-color)', color: 'var(--text-color)', fontSize: 12 };
const mapRow = { display: 'grid', gridTemplateColumns: 'minmax(120px, 1fr) minmax(0, 1.4fr)', gap: 10, alignItems: 'start', padding: '8px 10px', border: '1px solid var(--border-color)', borderRadius: 10, background: 'var(--bg-color)' };
const linkBtn = { background: 'none', border: 'none', padding: 0, font: 'inherit', fontSize: 12, color: 'var(--info)', cursor: 'pointer', textDecoration: 'underline' };
const scrollBox = { overflow: 'auto', maxHeight: 200, border: '1px solid var(--border-color)', borderRadius: 8 };
const table = { borderCollapse: 'collapse', width: '100%', fontSize: 12 };
const th = { textAlign: 'left', padding: '6px 8px', borderBottom: '1px solid var(--border-color)', position: 'sticky', top: 0, background: 'var(--card-bg)', whiteSpace: 'nowrap' };
const td = { padding: '5px 8px', borderBottom: '1px solid var(--border-color)', overflowWrap: 'anywhere' };
