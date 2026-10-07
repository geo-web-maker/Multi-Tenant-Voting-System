// Position heading and candidate row for the blueprint ballot (BP-T4). Same data, same handlers as the default markup.
import { Icon } from '../../components/icons.jsx';
import { faceCropUrl } from '../../cloudinaryImage';
import { Avatar } from './primitives.jsx';

/** Keeps the `position-header` class: the print stylesheet targets it. */
export function PositionHeading({ children }) {
  return <h3 className="position-header bp-pos">{children}</h3>;
}

/** Tap-to-toggle row. Selected = accent border + outline + tick, so it never relies on colour alone. */
export function CandidateRow({ name, image, selected, onToggle }) {
  const onKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); }
  };
  return (
    <div className={`bp-cand${selected ? ' bp-on' : ''}`} role="button" tabIndex={0} aria-pressed={selected} onClick={onToggle} onKeyDown={onKeyDown}>
      <Avatar name={name} src={image ? faceCropUrl(image, 48, 48) : ''} />
      <b>{name}</b>
      <span className="bp-tick" aria-hidden="true">{selected && <Icon name="check" />}</span>
    </div>
  );
}
