// Blueprint login fields (BP-T3): same two inputs (names, keys, placeholders, handlers) plus real <label>s,
// reusing the placeholder wording. The typing-placeholder animation stays in VoterLoginInputs.
import { FieldLabel } from './primitives';

export default function VoterFields({ studentId, setStudentId, name, setName, idLabel = 'Student Registration Number', idPlaceholder, namePlaceholder }) {
  return (
    <>
      <FieldLabel htmlFor="voter-reg-no">{idLabel}</FieldLabel>
      <input
        key="voter-reg-no" id="voter-reg-no" name="voter-reg-no" className="bp-in"
        value={studentId} onChange={(e) => setStudentId(e.target.value)}
        placeholder={`${idLabel} e.g. ${idPlaceholder}`} autoComplete="off"
      />
      <FieldLabel htmlFor="voter-full-name">Full Name</FieldLabel>
      <input
        key="voter-full-name" id="voter-full-name" name="voter-full-name" className="bp-in"
        value={name} onChange={(e) => setName(e.target.value)}
        placeholder={`Full Name e.g. ${namePlaceholder}`} autoComplete="off"
      />
    </>
  );
}
