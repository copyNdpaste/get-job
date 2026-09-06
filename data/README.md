# Local data

`ats-boards.local.json` can extend the public direct-career-board catalog without committing
company watchlists. It must contain only public ATS board metadata and no candidate information.

Copy `backend/examples/candidate-profile.example.json` to
`data/candidate-profile.local.json` and replace the example with your own resume evidence.

Everything else in this directory is ignored by Git. Do not force-add candidate profiles,
resumes, exported databases, browser sessions, or model credentials.

Place the three private resume PDFs under `data/generated-resumes.local/`. Keep the exact
local filenames documented in the project README so the local preview links can find them.

Personal Markdown notes must use an ignored name such as `data/application-notes.local.md`.
Never put a real name, email address, phone number, resume excerpt, or private note into a
tracked `.md` file. Durable application state belongs in the local PostgreSQL volume.
