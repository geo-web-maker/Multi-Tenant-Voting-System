// Header status cell that keeps its own clock, so only this cell re-renders each second (not App).
import { StatusCell } from './primitives';
import { statusDetail } from './labels.js';
import { usePhase } from '../../usePhase';

export default function LiveStatus({ status }) {
  const { info, left } = usePhase(status);
  return <StatusCell phase={info?.state || null} detail={statusDetail(info, left, status)} />;
}
