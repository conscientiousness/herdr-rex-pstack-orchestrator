# Upstream update detection

## Sub-features

Compare the pinned `pstack` and `cursor-team-kit` trees in [upstream.json](../../../../skills/pstack-adapter/references/upstream.json) against upstream `HEAD`, reporting exact revisions and changed paths without modifying the checkout.

## How to get to it (user POV)

The daily GitHub Actions monitor and README badge run this script. Locally, you need Git, Python 3.11 or later, and network access to GitHub. Check `git --version` and `skills/pstack-adapter/references/upstream.json` first.

## Driving it with existing scripts

```bash
python3 scripts/check_upstream.py --output "$proof/upstream.json"
```

Check both the JSON output and the exit code: `0` means current, `1` means upstream has updates to review, and `2` means the check could not complete. Exit `1` is a valid detection result, not a script error. Reopen `$proof/upstream.json` after the script cleans up its temporary checkout. Pass `--manifest` to test against a historical pin without editing the tracked manifest.

## Gotchas

- This detects source drift only. It does not test runtime compatibility or apply upgrades.
- Do not edit the pin to fabricate drift unless you are testing update detection itself.
- Follow [compatibility.md](../../../../skills/pstack-adapter/references/compatibility.md) before applying detected updates.
