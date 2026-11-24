---
# MACHINE-READABLE STATUS. Read by any code gate that checks for approval.
# A template must NEVER read "approved". The signed original replaces this
# file at docs/BIOMETRIC_APPROVAL_RECORD.md and sets status: approved there.
document_type: biometric_approval_record
status: not_approved
status_reason: "Blank template. Not executed by any party."
template: true
version: "0.1"
supersedes: null
---

# POPIA Biometric Processing — Approval Record

**THIS IS A BLANK TEMPLATE. IT IS NOT AN APPROVAL.**

Nothing in this document authorises any processing. It records nothing that any
person has confirmed. Every field below is a blank for the company
representative and qualified South African legal counsel to complete.

Filling in this template does not constitute approval. Only a signed copy,
executed by both parties named in Part G, constitutes approval.

---

## How to use this document

1. Complete Parts A through F with the responsible company representative and
   South African legal counsel.
2. Both sign Part G.
3. Save the executed copy as `docs/BIOMETRIC_APPROVAL_RECORD.md` — note the
   absence of `_TEMPLATE` in that filename.
4. Set the machine-readable `status` field at the top of the executed copy to
   `approved`, and record the signing date and the names of both signatories.
5. Leave this template in place. Do not edit it in the process of executing.

If any part is incomplete, the record is not an approval. An approval with
blanks in it is worse than no approval, because it looks like one.

---

## Part A — Processing being approved

Describe exactly what the system will do. Vague descriptions cannot be approved.

| Field | Entry |
|---|---|
| Modality (fingerprint / face / both) | |
| Where matching occurs (on-device / server / third-party service) | |
| Is any biometric data transmitted off the device? | |
| If yes, to whom, under what agreement | |
| Is a biometric template stored at all? | |
| If stored: encryption method and key custody | |
| Number of affected employees (estimated) | |
| Employee categories affected | |
| Countries/jurisdictions of affected employees | |

**Note:** if matching occurs entirely on a device and no template leaves it,
the analysis may differ substantially from server-side template storage.
Counsel must be told which it is. Answering "not sure yet" means the record
cannot be completed.

---

## Part B — Legal basis (counsel to complete)

Each item must be answered explicitly. "To be advised" is not an answer.

### B1. POPIA section 27 exception

Which exception in section 27(1) is relied upon?
