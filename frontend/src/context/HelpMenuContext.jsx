import React, { createContext, useContext, useState } from 'react';

const HelpMenuContext = createContext(null);

export function HelpMenuProvider({ children }) {
  const [open, setOpen] = useState(false);
  const [showRegister, setShowRegister] = useState(false);

  const value = {
    open,
    toggle: () => setOpen(o => !o),
    close: () => setOpen(false),
    showRegister,
    openRegister: () => { setShowRegister(true); setOpen(false); },
    closeRegister: () => setShowRegister(false),
  };

  return (
    <HelpMenuContext.Provider value={value}>
      {children}
    </HelpMenuContext.Provider>
  );
}

export function useHelpMenu() {
  const ctx = useContext(HelpMenuContext);
  if (!ctx) throw new Error('useHelpMenu must be used within a HelpMenuProvider');
  return ctx;
}
