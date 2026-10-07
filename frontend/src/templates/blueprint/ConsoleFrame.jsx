// Blueprint frame for the flat dashboards (BP-T7b). Reuses the existing `.dash-body` / `.dash-main` pair and its
// 768 px stacking rules from index.css; `bp-frame*` only exists so blueprint.css can address this case.
export default function ConsoleFrame({ nav = null, children }) {
  return (
    <div className="dash-body bp-frame">
      {nav}
      <div className="dash-main bp-frame-main">{children}</div>
    </div>
  );
}
