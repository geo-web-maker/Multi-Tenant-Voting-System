// Blueprint look of the OTP step (BP-T3). OtpInput owns all state/effects and passes the results in.
import OtpCells from './OtpCells';

export default function OtpScreen({
  otp, onChange, inputRef, phoneNumber, locked, lockLabel, hasError, feedback, disabled, isSubmitting, onVerify, onBack, help,
}) {
  return (
    <div style={{ textAlign: 'center' }}>
      <h2 id="bp-otp-title">
        Confirm the code sent to <span className="bp-num">{phoneNumber}</span>
      </h2>
      <OtpCells value={otp} hasError={hasError} locked={locked}>
        <input
          ref={inputRef} type="text" inputMode="numeric" pattern="[0-9]*" autoComplete="one-time-code" value={otp}
          placeholder="· · · · · ·" disabled={locked} aria-labelledby="bp-otp-title"
          onChange={onChange}
          className="bp-otp-input"
        />
      </OtpCells>
      {locked && (
        <p key="locked" role="alert" className="bp-alt msg-fade-in">
          Too many incorrect codes. You can try again in <b>{lockLabel}</b>. You do not need to do anything.
        </p>
      )}
      {hasError && <p key="error" role="alert" className="bp-alt msg-fade-in">{feedback.message}</p>}
      {feedback?.reason === 'no_live_code' && (
        <p key="no-code" role="alert" className="bp-ban bp-warn msg-fade-in">{feedback.message}</p>
      )}
      <div className="bp-row2">
        <button type="button" className="bp-btn bp-ghost" onClick={onBack}>Back</button>
        <button type="button" className="bp-btn" data-track="otp-submit" onClick={onVerify} disabled={disabled}>
          {isSubmitting ? 'Verifying…' : 'Verify Account'}
        </button>
      </div>
      {help && (locked || hasError) && (
        <a className="bp-lnk" href={help} target="_blank" rel="noopener noreferrer" style={{ display: 'block' }}>
          Need help? Contact support on WhatsApp
        </a>
      )}
    </div>
  );
}
