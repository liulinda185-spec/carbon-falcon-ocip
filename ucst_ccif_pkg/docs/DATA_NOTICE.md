# Data notice — template

> **This is a template, not legal advice.** Fill in the bracketed fields and
> have it reviewed by whoever handles data protection at your institution
> before you publish a link that accepts uploaded files. If the data will feed
> a paper, the ethics approval comes *before* collection, not after.

---

**Who operates this deployment.** [Operator name], [department], [institution].
Contact for anything on this page: [email address].

**What is collected when you upload a ledger.**

- the file you upload, stored row by row;
- its filename, row count, column names and SHA-256 checksum;
- the audit parameters you set (area, claimed removal, grid region) and the
  resulting report;
- your email address, as returned by the sign-in provider;
- any feedback you submit, plus a reply address if you choose to give one;
- **which step of the interface you reached**: opened the app, accepted this
  notice, loaded the sample, uploaded a ledger, ran the audit, exported the PDF,
  opened the feedback box — each with a timestamp and your email. Nothing you
  type is captured, and no IP address or browser fingerprint is stored. This is
  used only to find where testers get stuck.

**Why.** To run the audit; to let any audit output be traced back to the exact
bytes that produced it; and to keep one organisation's ledgers separate from
another's.

**Lawful basis.** Your consent, given by ticking the acknowledgement in the app
before the first upload. Withdrawing consent means asking us to delete what you
sent.

**Who can see it.** People whose email address is mapped to your organisation
in this deployment's configuration, and the operator. Not other organisations,
and not the public.

**How long it is kept.** Until you ask for deletion. Ledger rows are
append-only: correcting a file creates a new version rather than overwriting the
old one, so earlier audit certificates keep pointing at the data they actually
read.

**Deletion.** Email [address] stating the organisation and site to remove. We
delete that site's ledger rows, audit runs, feedback and step events, and
confirm within [number] working days.

**What we do not collect.** Payment details, HR records, or personal data
beyond your sign-in address. Please do not upload personal data or company
data you are not authorised to share.

**Research use — keep exactly one of these, delete the other.**

- (a) Audits are performed for the uploading organisation only. Nothing
  uploaded is used in any publication or external report.
- (b) Aggregate, non-attributable results may be used in research and
  publications; no individual file is ever published or shared. Ethics
  approval: [CityU HREC reference].

**Your rights.** Under the Personal Data (Privacy) Ordinance (Cap. 486) you may
request access to, and correction of, the personal data we hold about you.
Requests to [address].
