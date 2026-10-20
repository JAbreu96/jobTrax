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
BUNDLE_PREFIX=com.example scripts/launchd/build-wrapper.sh inbox-triage "Inbox Triage"

sed -e "s#REPO_PATH#$PWD#g" -e "s#HOME_PATH#$HOME#g" \
    scripts/launchd/com.example.inbox-triage.plist.example \
    > ~/Library/LaunchAgents/com.example.inbox-triage.plist

launchctl load ~/Library/LaunchAgents/com.example.inbox-triage.plist
launchctl list | grep com.example        # loaded?
```

`launchctl unload <path>` stops one. Rename the `com.example.` prefix to
whatever you like — the label inside the file must match the filename.

## Wrapper apps

Each plist runs its script through a small app in `~/Applications/Agents/`,
not through `/bin/bash`. macOS names a background item, and every permission
prompt, after the process launchd started, never after the label. With
`/bin/bash` that meant a row of identical "bash" entries in Login Items. Privacy
prompts were worse: macOS skipped bash and blamed the Claude CLI binary by its
filename, so the prompt read *"2.1.304" would like to access files in your
Documents folder*. The grant was tied to that versioned path, so it reset on
every CLI update, and an unattended run sat blocked on the prompt for hours.

A wrapper app takes the blame under its own name ("Inbox Triage would like
to access…"), and a grant sticks to the app across Claude updates.

Build the app before loading its plist. `BUNDLE_PREFIX` should match your
label prefix, and the display name must match the path in the plist:

```bash
while IFS='|' read -r id name; do
  BUNDLE_PREFIX=com.example scripts/launchd/build-wrapper.sh "$id" "$name"
done <<'EOF'
application-digest|Application Digest
applypass-inbound|ApplyPass Inbound
archive-jobs|Archive Jobs
claude-remote-control|Claude Remote Control
export-jobs-csv|Export Jobs CSV
follow-up-reminder|Follow-up Reminder
inbox-triage|Inbox Triage
work-search-record|Work Search Record
EOF
```

`launcher.c` spawns the script and waits rather than exec-ing it; exec would
hand the identity straight back to bash. The app is ad-hoc signed, so its
identity is a hash of the binary: a rebuild that changes the binary makes macOS
ask for each permission again. Each job asks once, on its first run after the
switch, so expect one prompt per job.

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
