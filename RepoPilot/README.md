# RepoPilot — Portable GitHub Multi-Account Uploader

RepoPilot is a Windows desktop app with independent account workspaces. Open multiple windows in one running app, connect each window to a different GitHub account, and manage or upload content to each account's repositories.

## Features
- Redesigned colorful interface with clearly highlighted primary, secondary, success, and destructive actions.
- One-click global Light and Dark theme switch, available in the launcher and every account workspace.
- Theme-aware cards, inputs, repository controls, activity log, and upload footer.
- Redesigned colorful interface with clearly highlighted primary, secondary, success, and destructive actions.
- One-click global Light and Dark theme switch, available in the launcher and every account workspace.
- Theme-aware cards, inputs, repository controls, activity log, and upload footer.
- Redesigned colorful interface with clearly highlighted primary, secondary, success, and destructive actions.
- One-click global Light and Dark theme switch, available in the launcher and every account workspace.
- Theme-aware cards, inputs, repository controls, activity log, and upload footer.
- Multiple independent account/workspace windows.
- GitHub Personal Access Token authentication with a dedicated Connect token button.
- Buttons to open GitHub fine-grained or classic token creation pages, with the required permission guidance.
- GitHub browser sign-in using OAuth Device Flow when an OAuth App Client ID with Device Flow enabled is configured.
- Verify the signed-in account and automatically load all repositories after connection.
- Manual repository refresh and pagination for accounts with more than 100 repositories.
- Scrollable workspace with a permanently visible upload action bar when the window is resized.
- Responsive workspace layout with a minimum width suitable for compact windows.
- Responsive workspace layout with a minimum width suitable for compact windows.
- Responsive workspace layout with a minimum width suitable for compact windows.
- Select a repository from the list or enter `owner/repository` manually.
- Create folders inside a repository, including nested paths such as `my game/assets/images`.
- Create or update text/code files directly in a repository using the built-in file editor.
- Delete a file or an entire folder (including its tracked contents) from the selected branch in one commit, with a confirmation prompt.
- Upload a local project folder into the repository root or any subfolder, such as `my game`.
- Create the first commit in an empty repository and support the selected branch.
- Existing files at matching paths are updated; unrelated repository files are preserved.
- Delete repositories after typing the exact `owner/repository` name in a confirmation dialog.
- Access tokens remain in memory only and are not written to disk. The OAuth Client ID is saved locally in `github_oauth.json`; it is not a secret.

## Creating folders and files
1. Connect a GitHub account and select a repository.
2. Click **Create folder** and enter a repository-relative path, for example `my game` or `my game/assets`.
3. RepoPilot adds a `.gitkeep` file so GitHub preserves the folder even while it is empty. After creating a folder, it automatically fills the **Upload destination** field with that folder path.
4. Click **Create file** to write a text or code file. Enter its path, such as `my game/README.md`, and its contents.
5. To upload a local project into a folder, set **Upload destination** to `my game`, select the local folder, and click **Push Project to GitHub**. The local folder's contents are placed inside that repository path, not in an extra nested copy of the local folder name.

Leave **Upload destination** blank to upload to the repository root. Nested paths and folder names containing spaces are supported.

## GitHub sign-in and token options

RepoPilot supports two connection methods:

1. **Connect token:** paste a GitHub Personal Access Token into the token field and click **Connect token**.
2. **Sign in with GitHub:** use the browser-based OAuth Device Flow. This requires a GitHub OAuth App Client ID whose Device Flow setting is enabled. Enter the public Client ID in the OAuth App Client ID field. The app stores this non-secret Client ID in `github_oauth.json` beside the portable app. No OAuth client secret is used by Device Flow.

To register an OAuth App for browser sign-in, the app publisher (or an advanced user) can open GitHub **Settings → Developer settings → OAuth Apps → New OAuth App**, register the app, enable **Device Flow** in its settings, and copy its **Client ID** into RepoPilot. A distributed build should normally be configured with the publisher's OAuth App Client ID before it is shared with end users. Do not put an OAuth client secret in the desktop app.

The **Generate fine-grained token** and **Generate classic token** buttons open the corresponding official GitHub pages. GitHub requires the user to create and approve the token; RepoPilot cannot mint a Personal Access Token by itself. For a fine-grained token, select the target repositories and grant **Contents: Read and write**. To delete repositories, also grant **Administration: Read and write**. For a classic token, `repo` and `delete_repo` scopes are needed for the full feature set. Classic tokens have broad access.

Browser sign-in requests the `repo` and `delete_repo` OAuth scopes so repository upload and repository deletion features can work. Use only an OAuth App you trust. GitHub password authentication is not supported.

## Deleting files and folders

1. Connect an account and select the repository and branch.
2. Click **Delete file/folder…**.
3. Enter a repository-relative path such as `my game/README.md` or `my game`.
4. Confirm the operation. If the path is a folder, RepoPilot removes that folder and its tracked contents from the selected branch in one commit.

Git does not track empty directories. Deleting a folder does not erase its previous versions from Git history; it removes the current branch's reference to that folder's contents. Very large repositories whose recursive Git tree is truncated by GitHub are rejected safely rather than partially deleted.

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
The app does not save your PAT or OAuth access token to a settings file. Closing a workspace window discards its access token from memory. The OAuth Client ID is public app configuration and is stored locally in `github_oauth.json`. Revoke tokens you no longer use from GitHub settings.
