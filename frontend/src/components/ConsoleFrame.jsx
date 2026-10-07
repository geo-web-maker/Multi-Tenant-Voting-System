import { getTemplate } from '../template';

// Frame for the FLAT admin dashboards (IT Admin, Financial Controller, Overseer, Vetting), BP-T7b.
//
//   <ConsoleFrame nav={<TabBar tabs={tabs} … />}> …tab content… </ConsoleFrame>
//
// Default template: a passthrough fragment, `nav` then `children`, so the DOM is exactly what
// `<TabBar …/>{content}` rendered before this seam existed.
// Blueprint: nav and content become siblings in a `.dash-body` row (rail on desktop, pill row on phones),
// the same layout the grouped dashboards (Super Admin, Commission) already use.
// No hooks here, so the early branch is safe (R12).
export default function ConsoleFrame({ nav = null, children }) {
  const bp = getTemplate();
  if (bp?.ConsoleFrame) return <bp.ConsoleFrame nav={nav}>{children}</bp.ConsoleFrame>;
  return <>{nav}{children}</>;
}
