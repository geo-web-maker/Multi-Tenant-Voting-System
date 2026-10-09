// Live version of derivePhase(): re-derives the phase and the countdown once a second, but only while there is a
// next milestone to count down to. Shared by the default PhaseBanner and the blueprint header status cell.
// (phase.js stays pure/React-free; this is the hook that sits on top of it.)
import { useEffect, useState } from 'react';
import { derivePhase, formatCountdown } from './phase';
import { parseUtc } from './tz';

/** status (from /election-status) -> { info, left }. `info` is derivePhase(...) or null; `left` is "02d 03h 04m 05s" or null. */
export function usePhase(status) {
  const [now, setNow] = useState(() => Date.now());
  const info = derivePhase(status, now);
  const target = info?.countdownTo ? parseUtc(info.countdownTo) : null;
  const targetMs = target ? target.getTime() : null;

  useEffect(() => {
    if (targetMs == null) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [targetMs]);

  const left = targetMs != null ? formatCountdown(targetMs - now) : null;
  return { info, left };
}
