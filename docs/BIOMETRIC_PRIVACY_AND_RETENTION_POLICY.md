# Biometric Privacy and Retention Policy

**Status: PROPOSED — NOT LEGALLY APPROVED**

**Version:** 0.2 (draft for counsel review; implementation status updated)
**Date recorded:** 2026-11-21
**Date revised:** 2026-11-24
**Approver:** _pending_

> This document states intended product policy. It is **not** a declaration of
> legal compliance and must not be treated as one. No biometric enrolment may
> occur until the approval gate in section 8 is satisfied and signed.

> Sections 1 and 5 describe controls that are now implemented in code. Section 2
> and section 8 remain unimplemented and blocked by the approval gate. Each
> section states which it is — a policy document that reads as though everything
> is done is worse than one that admits the gaps.

---

## 1. Raw photograph retention

**Status: implemented.**

- Do not retain raw facial photographs after the enrolment or verification
  process.
- Use temporary processing only where technically necessary.
- Securely delete temporary photographs after processing.
- Do not delete existing photographs until their current dependencies and legal
  implications have been investigated.
- Do not retain photographs simply because the storage system makes it
  convenient.

**Implementation.** A submitted photograph is decoded, magic-byte checked,
size-capped and virus-scanned, then discarded. `punch.photo_object_key` is
always `None` for new punches. Photographs captured before this control was
introduced are untouched and remain in storage; removing them requires the
dependency investigation described above and has not been attempted.

---

## 2. Biometric templates

**Status: not implemented. Blocked by section 8.**

- Store encrypted fingerprint or facial templates only where legally authorised
  and necessary.
- Do not store raw fingerprint images.
- Do not retain unnecessary raw facial images.
- Retain templates only while enrolment remains necessary and lawful.
- On employee departure, withdrawal of consent where applicable, or termination
  of the lawful purpose, revoke enrolment and securely delete templates unless a
  documented legal requirement justifies temporary retention.
- Record revocation and deletion in an audit trail **without** retaining the
  biometric template itself.

**Implementation.** No template is captured, stored, compared or deleted,
because no such capability exists. The `biometric_consent` and
`biometric_enrolment` tables exist in the tenant schema but are written by no
code path. A clock-in performs no biometric comparison: the employee code is
self-declared and the photograph is discarded after validation. This system
currently records *location and time*, not identity.

---

## 3. Legal basis

Do not assume that an employment contract or a general legitimate-interest
argument automatically authorises processing of biometric special personal
information.

South African legal counsel must confirm:

- The applicable POPIA section 27 exception.
- Whether consent is appropriate and sufficiently voluntary in an employment
  relationship.
- What employee notices and documentation are required.
- Whether any additional Information Regulator authorisation or requirements
  apply.
- The legal implications of providing biometric and non-biometric alternatives.

**Do not create the first biometric enrolment record until this written legal
confirmation exists.**

---

## 4. Non-biometric alternative

- A non-biometric attendance alternative is **mandatory**.
- Design for badge/PIN with HR oversight, subject to security review.
- Employees must not be unfairly disadvantaged because they use the alternative
  rather than biometric verification.

**Implementation note.** The current clock-in path is code-plus-photo, which is
non-biometric in effect. It is not a designed alternative, and it must not be
presented as one. A deliberate badge/PIN flow with HR oversight remains to be
built.

---

## 5. GPS coordinate retention

**Status: implemented, with a stated backup residual.**

Proposed initial policy:

- Raw employee GPS coordinates: **30 days**.
- Longer retention only where a documented dispute, investigation or legal hold
  requires it.
- Attendance verification verdicts and necessary audit evidence: retain
  according to an approved attendance/payroll retention schedule.
- Do not retain raw coordinates indefinitely by default.

### 5.1 What is implemented

Raw coordinates are stored in a dedicated `punch_location` table, separate from
the attendance punch record. This separation is not cosmetic: the punch table is
append-only at the database level — `UPDATE` and `DELETE` are both revoked and a
trigger raises — so a column that must expire cannot live there. While the
coordinates sat on the punch row, "deletion" was impossible by construction.

A scheduled sweep deletes `punch_location` rows older than 30 days. The punch
record itself is never modified, and it keeps permanently:

- the geofence verdict (inside / outside / inconclusive / unavailable),
- the reason for that verdict,
- a coarse distance band (within / near / distant) rather than an exact
  distance.

This distinction is deliberate. An audit needs to know *whether* a punch was
inside the authorised area and roughly how far outside; it does not need to know
precisely where the employee was standing. An exact distance combined with a
known site address narrows a position to a small ring, so it is deleted with the
coordinates rather than retained.

**Legal holds.** An open attendance exception for an employee on a given work
date suspends deletion of that day's coordinates until the exception is resolved
or dismissed. Resolving the exception releases the hold automatically; there is
no separate flag to clear and therefore no way to forget to clear it.

A finalised (locked) payroll period does **not** hold coordinates. Locked days
remain locked indefinitely, so holding on them would mean indefinite retention
by another name — contrary to the core rule of this section. The verdict on the
punch already answers the payroll-audit question a locked period raises.

### 5.2 Backup retention — stated residual

A deletion removes the row from the live database. It does **not** remove the
coordinates from database backups taken before the deletion. The retention
tiers are therefore:

| Tier | Retention | Maximum coordinate age |
|---|---|---|
| Daily | 14 days | 14 days |
| Weekly | 8 weeks | 56 days |
| Monthly | 12 months | ~365 days |

**A coordinate can therefore survive for up to approximately 12 months in a
monthly archive, against 30 days in the live database.** This policy does not
claim immediate secure deletion, and any statement that it does would be
inaccurate.

Restoring a backup taken before a purge returns those coordinates as live rows.
The recovery procedure therefore requires, as a hard gate before traffic
resumes, that the retention sweep be run against the restored database and
verified to leave zero expired rows. The sweep filters on age relative to the
present, not on provenance, so a single run clears any restored data.

Operational detail is in `docs/RETENTION_OPERATIONS_RUNBOOK.md`.

---

## 6. Location privacy

- Capture location only at authorised attendance events.
- No continuous tracking.
- No sending employee coordinates to Google or other third-party geocoding
  services.
- Restrict access to location history.
- Record access to sensitive location information.

**Implementation.** Location is read once at clock-in via the browser's
geolocation API with high accuracy enabled and caching disabled. No background
or continuous capture exists. Distance is computed locally by haversine against
the site's stored coordinates; nothing is sent to an external service. Retention
sweeps write an audit record of their own execution that contains counts and no
coordinates.

---

## 7. Security

Require:

- Encryption of biometric templates.
- Strict tenant isolation.
- Role-based access.
- Access logging.
- Secure deletion.
- Documented retention rules.
- Incident-response procedures.
- Written operator agreements where third parties process personal information.

**Implementation status by item.** Tenant isolation, role-based access and
access logging are in place and enforced at the database level. Secure deletion
is implemented for coordinates (see 5.1) and not applicable to templates, which
do not exist. Encryption of biometric templates is not implemented because there
are no templates. Incident-response procedures and written operator agreements
are organisational controls outside this codebase and are not evidenced by it.

---

## 8. Approval gate

These are proposed product decisions, not a declaration of legal compliance.

Before Phase 6, produce a written POPIA approval record signed off by the
responsible company representative and qualified South African legal counsel.
The approval record must specify the lawful basis, section 27 exception, employee
notice, consent requirements, fallback procedure, retention periods, deletion
procedure and security safeguards.

Until then:

- No biometric enrolment API.
- No biometric template writes.
- No new employee biometric enrolment records.
- No facial or fingerprint collection.
- No production biometric activation.

**This gate is currently unsatisfied.** No approval record exists, signed or
otherwise. Development work that would make any of the five prohibitions above
possible must not begin, even where it would be technically straightforward.

Testing face recognition against the developer's own face, on a development
machine, is not processing an employee's biometric data and is not covered by
this prohibition. Building the enrolment pipeline that captures or stores
employee templates is.

---

## Appendix A — Questions referred to counsel

1. Which POPIA section 27 exception applies to attendance biometrics in an
   employment relationship, if any?
2. Is employee consent capable of being validly obtained given the power
   imbalance, or must the basis rest elsewhere?
3. Is prior authorisation from the Information Regulator required for this
   processing?
4. What must the employee notice contain, and when must it be given?
5. Is the proposed 30-day raw-coordinate retention defensible? What retention
   applies to verification verdicts?
6. What is required to make secure deletion demonstrable for audit purposes?
7. Does storing any biometric template at all change the analysis compared with
   device-bound verification that stores none?
8. Is a ~12-month maximum coordinate lifetime in backup archives consistent with
   the retention representation made to employees, or does it require separate
   disclosure?

*These are questions for qualified counsel. Nothing in this document answers
them.*