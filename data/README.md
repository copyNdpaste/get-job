# Local data

Real candidate profiles and career direction belong in the local PostgreSQL
`candidate_profiles` table. Startup never imports local profile JSON files.
Only the synthetic profile under `backend/examples/` may be committed.

Legacy private source documents can be preserved in `private_documents` before
removing local originals after a verified database commit. Do not recreate
profile JSON, resume text or private review exports under this directory.

`ats-boards.local.json` may contain public ATS board metadata, never candidate data.
Everything except this README and `.gitkeep` is ignored. Database exports,
browser sessions, credentials and private resume attachments must never be force-added.
