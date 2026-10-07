import '@testing-library/jest-dom';
import { useBlueprint, envIsBlueprint } from './template';

// L3b parity net: `VITE_UI_TEMPLATE=blueprint npm test` runs the whole suite with the template registered.
// eslint-disable-next-line react-hooks/rules-of-hooks -- plain async helper, not a React hook
if (envIsBlueprint) await useBlueprint();
