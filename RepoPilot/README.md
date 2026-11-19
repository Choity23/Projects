# RepoPilot — Portable GitHub Multi-Account Uploader

RepoPilot is a Windows desktop application for managing GitHub repositories through a graphical interface. Open multiple independent account workspaces, connect each one to a different GitHub account, and upload or manage repository content without using command-line tools.

## Features

- Multiple independent GitHub account workspaces in one app.
- Connect using a GitHub Personal Access Token or browser sign-in through OAuth Device Flow.
- Automatic repository loading after connection, manual refresh, and pagination.
- Create public or private GitHub repositories, optionally initialized with a README.
- Browse mounted Windows drives (including removable and mapped drives) using the DRIVE dropdown in the local folder browser.
- Select a local project folder and upload its contents to the repository root or a nested destination.
- Support empty repositories by creating the initial commit when uploading.
- Create nested repository folders and text/code files with the built-in editor.
- Browse the remote repository tree and quickly delete a selected file or folder.
- Quickly delete a repository after a confirmation prompt.
- Right-click Cut, Copy, Paste and Select All in editable fields, plus standard keyboard shortcuts.
- Colorful interface with Light and Dark themes.
- Scrollable workspace and fixed upload controls for smaller windows.
- Activity log and upload progress display.
- Copyright and proprietary-use information in the About panel and package notices.

## Connect to GitHub

### Personal Access Token

1. Open an account workspace.
2. Paste a GitHub Personal Access Token into the masked token field.
3. Click **Connect Token**.
4. RepoPilot verifies the account and loads its repositories.

The **Generate fine-grained token** and **Generate classic token** buttons open GitHub's official token-creation pages. GitHub requires the user to create and approve the token; RepoPilot cannot mint one independently.

For a fine-grained token, select the repositories to manage and grant **Contents: Read and write** for uploads and file editing. Repository creation requires the repository-creation permission or **Administration: Read and write**, depending on the GitHub token options available. Repository deletion requires **Administration: Read and write**. For a classic token, `repo` and `delete_repo` scopes are needed for the full feature set. Classic tokens have broad access.

### Browser sign-in

Browser sign-in uses GitHub OAuth Device Flow and requires an OAuth App Client ID with Device Flow enabled. Enter the public Client ID in the **OAuth App Client ID** field. The app stores this non-secret value in `github_oauth.json`. Do not put an OAuth client secret in the desktop app.

## Create repositories, files and folders

1. Connect a GitHub account and select a repository, or click **Create New GitHub Repository**.
2. Use **Create Folder** to create a repository-relative path such as `my game/assets/images`. RepoPilot adds a `.gitkeep` file so GitHub preserves a newly created empty folder.
3. Use **Create File** to create or update a text/code file. Enter its path and contents in the editor, then save.
4. To upload a local project into a nested folder, enter that path in **Upload destination**, select the local folder, and click **Push Project to GitHub**.

Leave **Upload destination** blank to upload to the repository root. Existing files at matching paths are updated; unrelated remote files are preserved. Local empty folders are not uploaded because Git does not track empty directories.

## Quick-delete files, folders and repositories

1. Connect an account and select the repository and branch.
2. Click **Quick Delete File / Folder**.
3. Expand the repository tree and select a file or folder.
4. Click **Delete Selected** and approve the confirmation. No path typing is required.
5. To delete a repository, click **Quick Delete Repository** and approve the confirmation.

Deleting a folder removes its tracked contents from the selected branch in one commit. Deleting a repository is permanent and removes its files, issues, pull requests, and Git history from GitHub. Always verify the selected account and repository before confirming a destructive action.

## Local folder browser

The local browser displays files and folders and includes a **DRIVE** dropdown for mounted Windows drives. Choose C:, D:, removable storage, or a mapped drive reported by Windows, then browse its contents. RepoPilot reads the local folder or file selected for an upload; it does not need to scan the whole computer.

## Security and privacy

- GitHub access tokens are held in memory for the connected workspace and are not written to the app's settings files.
- The token entry is cleared after successful connection. Disconnect or close a workspace to clear the app's token references. Python cannot guarantee secure zeroization of strings from process memory.
- Each workspace has an independent GitHub session.
- GitHub writes, uploads, file/folder deletions, and repository deletions are performed through visible controls and confirmation dialogs.
- Repository deletion is irreversible. Use narrowly scoped tokens and revoke tokens that are no longer needed.
- The OAuth Client ID is public configuration, not an access token, and is stored locally in `github_oauth.json`.

See [SECURITY.md](SECURITY.md) for release-hardening guidance and limitations.

## Build the portable Windows executable

1. On Windows, install Python 3.11 or newer from https://www.python.org/downloads/windows/ and enable **Add Python to PATH**.
2. Extract this ZIP.
3. Double-click `BUILD-WINDOWS.bat` for the preferred Nuitka build.
4. The executable will be created at `dist\RepoPilot.exe`.

`BUILD-WINDOWS-COMPATIBLE.bat` creates a PyInstaller compatibility build. Build the Windows EXE on Windows; these scripts do not cross-compile the Windows application from Linux.

## Run from source

```powershell
py -3 repilot.py
```

## Limitations

- GitHub blocks individual files larger than 100 MB through the standard upload method.
- A single push is limited to 5,000 files.
- GitHub API rate limits apply; very large projects may take time.
- `.git` metadata is excluded from local uploads.
- Empty local folders are not uploaded. Git does not track empty directories; use **Create folder** to preserve one with `.gitkeep`.
- The built-in file editor creates text/code files. Binary files can be added through a local folder upload.
- The app updates matching remote file paths but does not delete remote files that are absent from the local folder.
- The selected upload destination is a repository-relative path, not a local PC path.

## Copyright

Copyright © 2026 Mst. Choity Akter. All rights reserved. See `COPYRIGHT.txt` and `LICENSE-PROPRIETARY.txt`.
