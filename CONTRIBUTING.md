# Contributing Guide

This guide walks you through contributing to our repositories.

## Prerequisites

- Git installed on your machine
- Access to the repository (you should be added as a collaborator)

---

## Step 1: Clone the Repository

Clone the repo to your local machine (only needed once per project):

```bash
git clone https://github.com/dsc-jssstu/dsc-recruitment-platform.git
```

Then navigate into the project folder:

```bash
cd <project_name>
```

---

## Step 2: Check Your Current Status

Before making changes, verify you're on the correct branch:

```bash
git status
```

This shows your current branch and any uncommitted changes.

---

## Step 3: Get the Latest Changes

Always pull the latest code from `main` before starting new work:

```bash
git pull origin main
```

This ensures you're working with the most up-to-date code and avoids merge conflicts.

---

## Step 4: Create or Switch to a Branch

**Never work directly on `main`.** Create a new branch for your feature or fix.

### Create a new branch:

```bash
git checkout -b your-branch-name
```

### Switch to an existing branch:

```bash
git checkout your-branch-name
```

**Branch naming tips:**
- Use descriptive names: `add-login-page`, `fix-navbar-bug`, `update-readme`
- Keep it lowercase with hyphens

---

## Step 5: Make Your Changes

Edit, add, or delete files as needed for your task.

---

## Step 6: Stage Your Changes

Add the files you want to commit:

### Add a specific file:

```bash
git add path/to/file
```

### Add all changed files:

```bash
git add .
```

---

## Step 7: Commit Your Changes

Save your staged changes with a descriptive message:

```bash
git commit -m "Add login form validation"
```

**Good commit messages:**
- Start with a verb: Add, Fix, Update, Remove, Refactor
- Be specific: "Fix navbar overlap on mobile" not "Fixed stuff"

---

## Step 8: Push Your Branch

Push your branch to the remote repository:

### First push (sets upstream):

```bash
git push -u origin your-branch-name
```

### Subsequent pushes:

```bash
git push
```

---

## Step 9: Create a Pull Request

1. Go to the repository on GitHub
2. Click **"Compare & pull request"** (appears after pushing)
3. Add a title and description of your changes
4. Request a review if required
5. Click **"Create pull request"**

Wait for approval before merging.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Clone repo | `git clone <url>` |
| Check status | `git status` |
| Pull latest | `git pull origin main` |
| New branch | `git checkout -b branch-name` |
| Switch branch | `git checkout branch-name` |
| Stage files | `git add .` |
| Commit | `git commit -m "message"` |
| Push | `git push -u origin branch-name` |

---

## Database Migrations

This project uses **Alembic** for database schema migrations. Never modify the database schema directly.

### Apply Migrations

Run this after pulling new changes that include migrations:

```bash
cd apps/backend
alembic upgrade head
```

### Create a New Migration

After modifying models (adding/changing tables or columns):

```bash
cd apps/backend
alembic revision --autogenerate -m "Description of changes"
```

Review the generated migration file in `alembic/versions/` before committing.

### Rollback a Migration

To undo the last migration:

```bash
cd apps/backend
alembic downgrade -1
```

### Migration Best Practices

- Always review auto-generated migrations before applying them
- Test migrations on a copy of the database first
- Never edit migrations that have been pushed to main
- Include migration files in your pull requests when you change models

---

## Common Issues

### "Your branch is behind"

Run `git pull origin main` to sync with the latest changes.

### Merge conflicts

1. Open the conflicting files
2. Look for `<<<<<<<`, `=======`, `>>>>>>>` markers
3. Keep the code you want, remove the markers
4. Stage and commit the resolved files

### Pushed to wrong branch

Contact a maintainer to help fix it.
