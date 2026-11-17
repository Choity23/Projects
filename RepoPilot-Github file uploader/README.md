# RepoPilot — Portable GitHub Multi-Account Uploader

RepoPilot is a Windows desktop app with independent account workspaces. Open multiple windows in one running app, connect each window to a different GitHub account, and manage or upload content to each account's repositories.

## Features
- Multiple independent account/workspace windows.
- GitHub Personal Access Token authentication.
- Verify the signed-in account and automatically load all repositories after connection.
- Manual repository refresh and pagination for accounts with more than 100 repositories.
- Scrollable workspace with a permanently visible upload action bar when the window is resized.
- Select a repository from the list or enter `owner/repository` manually.
- Create folders inside a repository, including nested paths such as `my game/assets/images`.
- Create or update text/code files directly in a repository using the built-in file editor.
- Upload a local project folder into the repository root or any subfolder, such as `my game`.
- Create the first commit in an empty repository and support the selected branch.
- Existing files at matching paths are updated; unrelated repository files are preserved.
- Delete repositories after typing the exact `owner/repository` name in a confirmation dialog.
- Tokens remain in memory only and are not written to disk.

## Creating folders and files
1. Connect a GitHub account and select a repository.
2. Click **Create folder** and enter a repository-relative path, for example `my game` or `my game/assets`.
3. RepoPilot adds a `.gitkeep` file so GitHub preserves the folder even while it is empty. After creating a folder, it automatically fills the **Upload destination** field with that folder path.
4. Click **Create file** to write a text or code file. Enter its path, such as `my game/README.md`, and its contents.
5. To upload a local project into a folder, set **Upload destination** to `my game`, select the local folder, and click **Push Project to GitHub**. The local folder's contents are placed inside that repository path, not in an extra nested copy of the local folder name.

Leave **Upload destination** blank to upload to the repository root. Nested paths and folder names containing spaces are supported.

## GitHub token permissions
For normal repository management and uploads, use a Personal Access Token with access to the target repository and **Contents: Read and write** permission. Repository deletion additionally requires **Administration: Read and write** for a fine-grained token, or the `delete_repo` scope for a classic token. GitHub password authentication is not supported; use a PAT. Create tokens only on GitHub's official website and never share them.

## Build the portable Windows EXE
1. On Windows, install Python 3.11 or newer from https://www.python.org/downloads/windows/ and enable **Add Python to PATH**.
2. Extract this ZIP.
3. Double-click `BUILD-WINDOWS.bat`.
4. The executable will be created at `dist\RepoPilot.exe`. Copy the EXE to a folder or USB drive to use it as a portable app.

The EXE is built on the Windows machine because PyInstaller does not cross-compile Windows executables from Linux.

## Run from source
```powershell
py -3 repilot.py
```

## Upload notes and limitations
- GitHub blocks individual files larger than 100 MB in normal repositories; RepoPilot rejects those files.
- A single push is limited to 5,000 files.
- GitHub API rate limits apply. Very large projects may take time.
- `.git` metadata is excluded from local uploads.
- Empty local folders are not uploaded. Git does not track empty directories; use **Create folder** to preserve one with `.gitkeep`.
- The built-in file editor creates text/code files. Binary files should be added through a local folder upload.
- The app updates matching file paths but does not delete remote files that are absent from the local folder.
- The selected upload destination is a repository-relative path. Do not enter a local PC path there.

## Privacy
The app does not save your PAT to a settings file. Closing a workspace window discards its token from memory. Revoke tokens you no longer use from GitHub settings.
