# Starting with the machine

`km boot --apply` makes the panel start with Ubuntu, as a systemd **user** unit — the same
shape as the esteira's `esteira boot --apply`. One server on `127.0.0.1:8431` serves every
project in your registry ([projects.md](projects.md)); the VS Code extension finds it already
up and only opens the browser.

```bash
km boot            # shows linger, the unit, where `code` was found, and the unit it would write
km boot --apply    # writes ~/.config/systemd/user/km.service, enables it and (re)starts it
```

## What `--apply` does

1. Writes `~/.config/systemd/user/km.service`, atomically. The file says it is **GENERATED**
   and from which commit: never edit it — edit `km/boot.py` and run `km boot --apply` again.
2. `systemctl --user daemon-reload`, `enable km.service`, `restart km.service`.
3. Waits for `http://127.0.0.1:8431/api/projetos` to answer; if it does not, it fails and
   says where to look (`journalctl --user -u km -n 30`).

Without `--apply` nothing is written and nothing starts.

## Why it is built this way

| Choice | Why |
|---|---|
| **The unit is generated, not hand-written** | a hand-edited unit drifts from the code that serves it; the header names the commit it came from |
| **The PATH is built, not copied** | the WSL `$PATH` carries Windows directories with spaces, and systemd cuts an unquoted `Environment=` at the first space. The unit's PATH has km, `/usr/local/bin:/usr/bin:/bin` (python, git) and VS Code's `bin`, **quoted whole** |
| **`code` is looked for in the PATH, then in the Windows install** (`/mnt/c/Users/*/AppData/Local/Programs/Microsoft VS Code/bin`) | a service has no VS Code terminal, which is where `code` usually comes from: without the second place, *abrir no VS Code* would never work in it |
| **`restart`, not `start`** | after an update the Python in memory is the old one; the page is read on every load, the server code is not |
| **Linger must be `yes`** | with `Linger=no`, closing the last WSL window stops every user unit. `km boot` shows it; `loginctl enable-linger $USER` turns it on (the esteira's `boot` already does) |

## Living with it

- **After updating km** (a `git pull`, a merge on master): `km boot --apply` — it rewrites the
  unit from the new commit and restarts the server.
- **Logs:** `journalctl --user -u km -f`.
- **Stop it for good:** `systemctl --user disable --now km` (the unit file stays; delete it
  from `~/.config/systemd/user/` if you want it gone).
- **A second panel** for testing a branch runs next to it on another port:
  `km serve --port 8451`.
