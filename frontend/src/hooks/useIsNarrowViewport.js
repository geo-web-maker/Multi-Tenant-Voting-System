import { useEffect, useState } from 'react';

/** True below 480 px wide, so charts can switch to a phone-sized viewBox. */
export default function useIsNarrowViewport() {
  const [narrow, setNarrow] = useState(() => typeof window !== 'undefined' && window.innerWidth < 480);
  useEffect(() => {
    const f = () => setNarrow(window.innerWidth < 480);
    window.addEventListener('resize', f);
    return () => window.removeEventListener('resize', f);
  }, []);
  return narrow;
}
