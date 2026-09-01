# Local Git Identity and First Commit

The Codex sandbox can edit the source tree but cannot write this repository's
`.git/index`. Run these commands once in a normal PowerShell terminal from the
project folder.

If Git first reports `detected dubious ownership`, add a trust exception for
only this exact project path, then continue. Do not use a wildcard or a broad
desktop/home-directory exception:

```powershell
git config --global --add safe.directory "C:/Users/comac/Desktop/Alpaca Trading Hack"
```

Then configure this repository's identity and create the first local commit:

```powershell
git config user.name "Options Alpha Solo"
git config user.email "YOUR_GITHUB_USERNAME@users.noreply.github.com"
git add -A
git status --short
git commit -m "Build guarded options paper-trading agent"
```

Use the exact GitHub-provided `...@users.noreply.github.com` address shown under
GitHub **Settings → Emails**. Do not put an Alpaca key, Featherless key, OpenAI
key, account ID, or personal address in the repository. `.env` is ignored; only
`.env.example` is intended for source control.

Before creating a public repository, inspect the staged filenames and run:

```powershell
git diff --cached --check
git grep --cached -n -I -E `
  -e "ALPACA_API_KEY=[^[:space:]]+" `
  -e "ALPACA_SECRET_KEY=[^[:space:]]+" `
  -e "FEATHERLESS_API_KEY=[^[:space:]]+" `
  -e "OPENAI_API_KEY=[^[:space:]]+" `
  -- ':!docs/local-git-setup.md' ':!scripts/release-preflight.ps1' ':!tests/test_submission_check.py'
```

The final command should return no matches. The repository's intentional
scanner examples are excluded by the release preflight; do not treat those
examples as credentials. Public repository creation and the
first push remain a separate, approval-gated step.

Before the first commit, run the read-only release gate. It does not stage,
commit, push, upload, deploy, or place an order:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/release-preflight.ps1
```

After inspecting `git add -A` output, use the staged variant to require a clean
staged diff and scan it for credential-like environment assignments:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/release-preflight.ps1 -RequireStaged
```
