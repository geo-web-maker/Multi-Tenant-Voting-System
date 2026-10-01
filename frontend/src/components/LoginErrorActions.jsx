import React from 'react';
import { useHelpMenu } from '../context/HelpMenuContext';
import { buildSupportLink } from '../supportLink';

const btn = { display: 'block', width: '100%', boxSizing: 'border-box', minHeight: 44, padding: '10px 14px', marginBottom: 10, borderRadius: 10,
  border: '1px solid var(--border-color)', background: 'var(--card-bg)', color: 'var(--text-color)', fontSize: 14, fontWeight: 600,
  textAlign: 'center', textDecoration: 'none', cursor: 'pointer' };

/**
 * Next-step buttons under a voter login error (guide 4.3). Rendered inside the Help provider so
 * "Check the voter register" can open the same register search as the Help menu.
 * `action` / `support` come from loginGuidance(); unknown errors pass neither and render nothing.
 * The prefilled support message never asks for the code.
 */
export default function LoginErrorActions({ action, support, supportContact = '', orgName = '', studentId = '', onNavigate }) {
  const { openRegister } = useHelpMenu();
  const supportHref = buildSupportLink(supportContact, orgName, studentId, 'I cannot log in to vote (never send your code)');
  const changeHref = buildSupportLink(supportContact, orgName, studentId, 'There is no phone number on file for me. Please add one (never send your code)');

  const items = [];
  if (action === 'check_register') {
    items.push(<button key="reg" type="button" style={btn} onClick={() => { onNavigate?.(); openRegister(); }}>Check the voter register</button>);
  }
  if (action === 'contact_change' && changeHref) {
    items.push(<a key="chg" href={changeHref} target="_blank" rel="noopener noreferrer" style={btn}>Request a contact change</a>);
  }
  if (support && supportHref) {
    items.push(<a key="sup" href={supportHref} target="_blank" rel="noopener noreferrer" style={{ ...btn, color: '#128C7E' }}>Contact support</a>);
  }
  return items.length ? <div>{items}</div> : null;
}
