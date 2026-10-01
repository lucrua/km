# Roadmap

Ordered by what unlocks the next thing. Nothing here is committed to a date.

## Now — the chancel

`serve · projects · pendente · chancela · restore · mv · forget · lint · marcas · quando · baseline`, over
`refs/km/chancela`: a reviewed copy of each file, compared with `git diff`, for the files
chosen in the panel's *Arquivos* view — one panel for every registered repository
([projects.md](projects.md)). The local panel and the VS Code extension read the
same state; agents follow [agents.md](agents.md). The model is in [chancel.md](chancel.md).

## Next

- **Deleting a passage that never had a chancel.** `restore` already reverts the hunk, which
  removes text an agent added; what is missing is the reason going somewhere other than the
  commit message.
- **A wider `km lint`** — today it checks the marks and config entries with nothing on disk.
  Still to come: a broken link, a source that does not exist.
- **The chancel outside the delivered `.git`.** For a repository handed over to someone
  else, an option to keep the ref in a git directory of its own per project (for example
  under `~/.local/share/km/<project>`) — still git's object store, as
  [chancel.md](chancel.md) argues, but never inside the copy that leaves.
- **The panel as cards.** One card per passage that needs a decision, with the sources next
  to it and an option to open a conversation from the card.
- **Dependencies across repositories.** A passage in one repository declares that it affects
  another; when its text changes, the dependent one is reported as suspect. The declaration
  lives on the side that may not be shared.
- **Session intake.** Turning what was decided in a conversation into proposed passages, so
  a decision does not stay only in a transcript.

## Deliberately out of scope

- **Deciding anything.** No LLM call, no network. The tool reports; a person chancels.
- **Confidence scores.** A number invented for a passage is false precision; what carries
  weight is the mark written next to it.
- **Locking and session coordination.** Editors already refuse stale writes, git already
  merges, and the panel shows both texts when the file moved under you.
- **Being a document editor.** The only writes are the ones you ask for: `restore`, the
  marks, and editing a passage.
