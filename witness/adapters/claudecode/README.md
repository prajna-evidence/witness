# claudecode adapter

Observes Claude Code by capturing hook payloads. Everything it produces is **tier C** —
self-reported, the agent talking about itself. No amount of local corroboration changes that (S3).

## Install the hook

In the observed repository's `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse":       [{ "hooks": [{ "type": "command", "command": "witness capture" }] }],
    "PostToolUse":      [{ "hooks": [{ "type": "command", "command": "witness capture" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "witness capture" }] }],
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "witness capture" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "witness capture" }] }]
  }
}
```

`capture` reads one payload from stdin, appends it to `.witness/raw/<session>.jsonl`, and exits 0.
It does nothing else, and it **cannot fail the agent** — a malformed payload, an unwritable
directory or a full disk all exit 0 with no record rather than breaking the session being observed.
A missing record is detectable afterwards; a broken agent is not recoverable.

## Normalise, later

```sh
witness normalize .witness/raw/<session>.jsonl
```

Nothing in this step runs during a session. That split is S10 and it is what makes Python viable
here.

## What it can and cannot see

`manifest.json` is the contract; the short version:

- **Sees:** tool calls and their targets, `permission_mode`, `effort`, session lifecycle, the user's
  submitted intent.
- **Cannot see, on the hook channel:** event timestamps (we stamp at capture, which may lag), model
  id, token counts, cost. Those live in the transcript — W2b.
- **Will not infer:** the SDLC phase of a shell command. `terraform apply` is obviously a deploy;
  the adapter still records `phase: null` with a reason, because the host did not say so and a
  guess promoted into evidence is the failure this format exists to prevent.
