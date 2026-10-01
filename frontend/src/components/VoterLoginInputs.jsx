import { useEffect, useState } from 'react';

// Sample IDs/names cycled in the login placeholder animation.
const examples = [
  { id: "23/U/BCS/10245/GV", name: "Ayebale Elizabeth" },
  { id: "22/U/ISD/08940/PD", name: "Namusoke Dorothy Nalwadda" },
  { id: "23/U/AGE/11223/GV", name: "Kaggwa Paul" },
  { id: "21/U/BSE/44556/PE", name: "Sserwadda Valentino" },
  { id: "23/U/BPH/00341/GV", name: "Bakanansa Jesca" }
];

// Owns the typing-placeholder animation state so each 40-120 ms tick
// re-renders only these two inputs, never App.
export default function VoterLoginInputs({ studentId, setStudentId, name, setName, inputStyle }) {
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
  }, [placeholderText, isDeleting, loopNum, typingSpeed, studentId, name]);

  return (
    <>
      <input
        key="voter-reg-no"
        name="voter-reg-no"
        style={inputStyle}
        value={studentId}
        onChange={e => setStudentId(e.target.value)}
        placeholder={`Student Registration Number e.g. ${placeholderText.id}`}
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
