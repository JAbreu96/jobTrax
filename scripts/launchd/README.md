# launchd templates

The scheduled skills run as launchd agents. The real plists live in
`~/Library/LaunchAgents/`, outside the repo, so these are templates.

Two placeholders to replace in each file you want:

| Placeholder | Replace with |
|---|---|
| `REPO_PATH` | the absolute path to your clone, e.g. `/Users/you/projects/agents` |
| `HOME_PATH` | your home directory, e.g. `/Users/you` |

launchd does not expand `~` or `$HOME` in a plist, which is why these are
absolute paths rather than variables.

```bash
sed -e "s#REPO_PATH#$PWD#g" -e "s#HOME_PATH#$HOME#g" \
    scripts/launchd/com.example.inbox-triage.plist.example \
    > ~/Library/LaunchAgents/com.example.inbox-triage.plist

launchctl load ~/Library/LaunchAgents/com.example.inbox-triage.plist
launchctl list | grep com.example        # loaded?
```

`launchctl unload <path>` stops one. Rename the `com.example.` prefix to
whatever you like — the label inside the file must match the filename.

## Before you load anything

Each `scripts/run-*.sh` hardcodes the toolchain launchd should use, because
launchd starts with a minimal `PATH`:

```bash
PYENV_BIN="$HOME/.pyenv/versions/3.10.3/bin"
export PATH="$PYENV_BIN:$HOME/.nvm/versions/node/v18.20.4/bin:..."
```

Both versions are almost certainly wrong for your machine. The Python one must
be the interpreter that has the `mcp` package installed, or the `job_tracker`
server dies on import and never registers — the run fails with no MCP tools and
no obvious reason why. The scripts check for it and exit 1 rather than degrade
silently.

The model is pinned (`--model claude-sonnet-5`) in every script on purpose: an
interactive `/model` change once silently repointed every scheduled job.

Logs land in `$HOME/Library/Logs/<job-name>/YYYY-MM-DD.log`.
