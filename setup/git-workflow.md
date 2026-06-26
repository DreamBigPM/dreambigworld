# The Git Workflow
### How to save your work, create a PR, and keep your code safe

---

You have a server. You have a GitHub repo. Now here's how they work together.

**The rule:** You never change `main` directly. You build on a branch,
open a PR, the checks run automatically, and then you merge. This is how
every professional development team on the planet works. Now it's how you work.

---

## Every Time You Build Something New

### Step 1 — Create a branch for your work

```bash
git checkout -b my-lease-tracker
```

Name it after what you're building. Use dashes, no spaces.

### Step 2 — Build your tool

Work with Jarvis as normal. Files get created in your `projects/` folder.

### Step 3 — Save your work to GitHub

```bash
git add .
git commit -m "add lease renewal tracker — flags leases expiring in 60 days"
git push origin my-lease-tracker
```

Write commit messages like a human. "add lease tracker" tells you what it does.
"wip" or "stuff" tells you nothing six months from now.

### Step 4 — Open a Pull Request

1. Go to **github.com/YOUR_USERNAME/wolf-pack**
2. You'll see a yellow banner: *"my-lease-tracker had recent pushes"*
3. Click **Compare & pull request**
4. Write a one-line description of what you built
5. Click **Create pull request**

### Step 5 — Watch the checks run

Two checks run automatically on every PR:

| Check | What It Does |
|---|---|
| Python syntax | Makes sure your code has no typos that would break it |
| Secret scan | Makes sure you didn't accidentally save your API key in a file |

Green ✓ = you're good. Red ✗ = something to fix before merging.

### Step 6 — Merge

Once checks pass:
1. Click **Merge pull request**
2. Click **Confirm merge**
3. Your code is now on `main` — the safe, stable version

### Step 7 — Clean up

Back on your server:
```bash
git checkout main
git pull origin main
git branch -d my-lease-tracker
```

You're back on `main` with your new tool included.

---

## The Golden Rule

**`main` is always working.** You never push broken code to `main`.
If something breaks on a branch, it stays on the branch until it's fixed.
`main` is the version you'd show an owner.

---

## Quick Reference

```bash
# Start new work
git checkout -b branch-name

# Save progress
git add .
git commit -m "what I built"
git push origin branch-name

# After merging, clean up
git checkout main
git pull origin main
git branch -d branch-name

# See what branch you're on
git branch

# See what changed
git status
```

---

## If Something Goes Wrong

**Pushed to main by accident:**
```bash
git checkout -b rescue-branch
git push origin rescue-branch
```
Then open a PR from that branch. Your work is safe.

**Merge conflict:**
Tell Jarvis: *"I have a merge conflict on [filename]. Help me resolve it without losing my work."*

**Lost track of what branch you're on:**
```bash
git branch
```
The branch with `*` is where you are.
