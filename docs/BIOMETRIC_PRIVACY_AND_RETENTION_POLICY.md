## 4. Non-biometric alternative

**Status: implemented.**

- A non-biometric attendance alternative is **mandatory**.
- Design for badge/PIN with HR oversight, subject to security review.
- Employees must not be unfairly disadvantaged because they use the alternative
  rather than biometric verification.

### 4.1 What exists

Two non-biometric paths exist, and they are not equivalent:

| Path | Verification | Notes |
|---|---|---|
| Employee code + photograph | **None** | The photograph is validated and then discarded under section 1, so it verifies nothing. Anyone who knows a code can clock in as that person. |
| Employee code + 6-digit PIN | Verified server-side | argon2 hash, five attempts, 15-minute lockout. |

The PIN is offered on the clock-in screen itself, alongside the camera path. It
is not mentioned only in HR documentation, because section 4 requires the
alternative to be genuinely available — an option an employee has to be told
about is available in principle and not in practice.

### 4.2 Honest limitations

A 6-digit PIN is **weaker than a biometric**: it can be shared, observed or
guessed. It is not represented as equivalent, and it must not be described to
employees as equally secure.

What it does provide is verifiable identity rather than none. The code-plus-photo
path provides no verification at all, so the PIN is a strict improvement on the
current default — and the PIN is the only path that constitutes a genuine
alternative to biometrics once biometrics exist.

A badge option would require reader hardware that the current terminal (a
browser on a phone or desktop) does not have. The verification shape is the same,
so it can be added as `method='badge'` when hardware exists.

### 4.3 No detriment

PIN punches are **not** flagged as exceptions and carry no UI marking. The
employee who chooses the non-biometric path is not treated as suspicious; the
choice is recorded in `punch.method` for HR reporting, and that is all.

HR sets, resets, clears and unlocks PINs. Self-service PIN change is not
implemented; when it is, it requires the employee's existing credential.