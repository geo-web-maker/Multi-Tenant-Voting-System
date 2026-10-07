// Six presentation cells over the ONE real input (F8/E6). The input keeps focus, autocomplete, inputMode and
// paste handling (all set by the caller); cells only mirror the digits. aria-hidden: a screen reader sees one field.
export default function OtpCells({ value, hasError = false, locked = false, children }) {
  const cells = Array.from({ length: 6 }, (_, i) => value[i] || '');
  return (
    <div className={`bp-otp${hasError ? ' bp-err' : ''}${locked ? ' bp-lock' : ''}`}>
      {cells.map((d, i) => <i key={i} aria-hidden="true">{d}</i>)}
      {children}
    </div>
  );
}
