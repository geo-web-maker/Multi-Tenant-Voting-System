import React, { createContext, useContext, useState } from 'react';

const HelpMenuContext = createContext(null);

export function HelpMenuProvider({ children }) {
  const [open, setOpen] = useState(false);
  const [showRegister, setShowRegister] = useState(false);
  const [showTimeline, setShowTimeline] = useState(false);
  const [showFees, setShowFees] = useState(false);

  const value = {
    open,
    toggle: () => setOpen(o => !o),
    close: () => setOpen(false),
    showRegister,
    openRegister: () => { setShowRegister(true); setOpen(false); },
    closeRegister: () => setShowRegister(false),
    showTimeline,
    openTimeline: () => { setShowTimeline(true); setOpen(false); },
    closeTimeline: () => setShowTimeline(false),
    showFees,
    openFees: () => { setShowFees(true); setOpen(false); },
    closeFees: () => setShowFees(false),
  };

  return (
    <HelpMenuContext.Provider value={value}>
      {children}
    </HelpMenuContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useHelpMenu() {
  const ctx = useContext(HelpMenuContext);
  if (!ctx) throw new Error('useHelpMenu must be used within a HelpMenuProvider');
  return ctx;
}
