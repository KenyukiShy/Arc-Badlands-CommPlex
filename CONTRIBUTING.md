# Contributing to Arc Badlands CommPlex

## Branch Strategy

```
master      ← Production. Protected. Architect-only merges.
  └── dev   ← Integration. All PRs target here.
        └── feat/INITIALS-ISSUE-slug   ← Your feature branch
```

**Branch naming:** `feat/KJ-42-twilio-serial-mode`
**Initials:** KJ = Kenyon, CC = Cynthia, CH = Charles, JM = Justin

## Commit Messages

Format: `type(scope): description`

| Type | Use For |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Adding/fixing tests |
| `refactor` | Code change, no new feature |
| `chore` | Tooling, deps, config |

Examples:
```
feat(api): add Twilio serial call endpoint
fix(core): correct sluice filter threshold
docs(readme): update codespaces setup steps
test(api): add webhook signature validation tests
```

## Pull Request Process

1. Branch from `dev`, never from `master`
2. Run `make test` — all 103 must pass
3. Run `make lint` — no linting errors
4. Open PR targeting `dev`
5. Fill in the PR template (description, testing steps, screenshots if UI)
6. Request review from at least 1 teammate
7. Squash merge after approval

## Domain Isolation Rules

- `CommPlexCore` **never** imports from `CommPlexAPI` or `CommPlexEdge`
- `CommPlexAPI` **may** import from `CommPlexSpec` and `CommPlexCore`
- `CommPlexEdge` **may** import from `CommPlexSpec` only
- All shared types and interfaces go in `CommPlexSpec`
- Violating domain isolation = PR rejected

## Secrets

- **Never** commit `.env`, `oauth_desktop_client_secret.json`, or any credential file
- All secrets live in GCP Secret Manager (`commplex-493805`)
- Use `bash gcp_secrets_sync.sh` to pull them to your local `.env`
- `.env` is in `.gitignore` — if you accidentally stage it, run `git rm --cached .env`

## Testing

```bash
make test           # Full suite (required before every PR)
make test-fast      # Skip slow integration tests
pytest tests/test_commplex.py::TestClassName::test_name  # Single test
```

New code requires new tests. Coverage should not decrease.

## Issue Labels

Use the S2S label system. Every issue needs at minimum:
- A `scope:` label
- A `P` priority label  
- A `status:` label
- A `type:` label

See `.github/ISSUE_TEMPLATE/` for templates.
