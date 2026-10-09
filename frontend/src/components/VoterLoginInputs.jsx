import { useEffect, useState } from 'react';
import { getTemplate } from '../template';
import { useIdText } from '../idText';

// Owns the typing-placeholder animation state so each 40-120 ms tick
// re-renders only these two inputs, never App.
export default function VoterLoginInputs({ studentId, setStudentId, name, setName, inputStyle }) {
  const idText = useIdText();
  // Sample IDs/names cycled in the placeholder animation: this organisation's own (Branding), else the defaults.
  const examples = idText.ids.map((id, i) => ({ id, name: idText.names[i % idText.names.length] }));
  const [placeholderText, setPlaceholderText] = useState({ id: "", name: "" });
  const [isDeleting, setIsDeleting] = useState(false);
  const [loopNum, setLoopNum] = useState(0);
  const [typingSpeed, setTypingSpeed] = useState(150);

  useEffect(() => {
    // Stop the animation if the user has already started typing
    if (studentId !== "" || name !== "") return;

    const handleTyping = () => {
      const i = loopNum % examples.length;
      const fullId = examples[i].id;
      const fullName = examples[i].name;

      const nextId = isDeleting
        ? fullId.substring(0, placeholderText.id.length - 1)
        : fullId.substring(0, placeholderText.id.length + 1);
      const nextName = isDeleting
        ? fullName.substring(0, placeholderText.name.length - 1)
        : fullName.substring(0, placeholderText.name.length + 1);

      setPlaceholderText({ id: nextId, name: nextName });

      const finishedTyping = !isDeleting && nextId === fullId && nextName === fullName;
      const finishedErasing = isDeleting && nextId === "" && nextName === "";

      let speed = isDeleting ? 40 : 120;
      if (finishedTyping) {
        speed = 2000; // hold the full text so students can read it
        setIsDeleting(true);
      } else if (finishedErasing) {
        setIsDeleting(false);
        setLoopNum(loopNum + 1);
        speed = 500;
      }
      setTypingSpeed(speed);
    };

    const timer = setTimeout(handleTyping, typingSpeed);
    return () => clearTimeout(timer);
  }, [placeholderText, isDeleting, loopNum, typingSpeed, studentId, name, idText]); // eslint-disable-line react-hooks/exhaustive-deps

  const bp = getTemplate();
  if (bp) {
    return <bp.VoterFields studentId={studentId} setStudentId={setStudentId} name={name} setName={setName} idLabel={idText.label} idPlaceholder={placeholderText.id} namePlaceholder={placeholderText.name} />;
  }
  return (
    <>
      <input
        key="voter-reg-no"
        name="voter-reg-no"
        style={inputStyle}
        value={studentId}
        onChange={e => setStudentId(e.target.value)}
        placeholder={`${idText.label} e.g. ${placeholderText.id}`}
        autoComplete="off"
      />
      <input
        key="voter-full-name"
        name="voter-full-name"
        style={inputStyle}
        value={name}
        onChange={e => setName(e.target.value)}
        placeholder={`Full Name e.g. ${placeholderText.name}`}
        autoComplete="off"
      />
    </>
  );
}
