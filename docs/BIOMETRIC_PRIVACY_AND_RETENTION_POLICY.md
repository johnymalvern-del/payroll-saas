# Biometric Privacy and Retention Policy

**Status: PROPOSED — NOT LEGALLY APPROVED**

**Version:** 0.1 (draft for counsel review)
**Date recorded:** 2026-11-21
**Approver:** _pending_

> This document states intended product policy. It is **not** a declaration of
> legal compliance and must not be treated as one. No biometric enrolment may
> occur until the approval gate in section 8 is satisfied and signed.

---

## 1. Raw photograph retention

- Do not retain raw facial photographs after the enrolment or verification
  process.
- Use temporary processing only where technically necessary.
- Securely delete temporary photographs after processing.
- Do not delete existing photographs until their current dependencies and legal
  implications have been investigated.
- Do not retain photographs simply because the storage system makes it
  convenient.

## 2. Biometric templates

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

## 4. Non-biometric alternative

- A non-biometric attendance alternative is **mandatory**.
- Design for badge/PIN with HR oversight, subject to security review.
- Employees must not be unfairly disadvantaged because they use the alternative
  rather than biometric verification.

## 5. GPS coordinate retention

Proposed initial policy:

- Raw employee GPS coordinates: **30 days**.
- Longer retention only where a documented dispute, investigation or legal hold
  requires it.
- Attendance verification verdicts and necessary audit evidence: retain
  according to an approved attendance/payroll retention schedule.
- Do not retain raw coordinates indefinitely by default.

## 6. Location privacy

- Capture location only at authorised attendance events.
- No continuous tracking.
- No sending employee coordinates to Google or other third-party geocoding
  services.
- Restrict access to location history.
- Record access to sensitive location information.

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

*These are questions for qualified counsel. Nothing in this document answers
them.*