# RepoPilot — Portable GitHub Multi-Account Uploader

RepoPilot is a Windows desktop app with independent account workspaces. Open multiple windows in one running app, connect each window to a different GitHub account, and manage or upload content to each account's repositories.

## Features
- Right-click Cut, Copy, Paste and Select all menus in editable fields and text areas.
- Clipboard shortcuts are activated automatically when you click or focus a text field, including fields in dialogs.
- Standard clipboard shortcuts: Ctrl+C, Ctrl+X, Ctrl+V and Ctrl+A.
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
- Select a repository from the list or enter `owner/repository` manually.
- Create folders inside a repository, including nested paths such as `my game/assets/images`.
- Create or update text/code files directly in a repository using the built-in file editor.
- Browse repository files and folders in an expandable tree, then quick-delete the selected file or an entire folder (including tracked contents) without typing its path.
- Upload a local project folder into the repository root or any subfolder, such as `my game`.
- Create the first commit in an empty repository and support the selected branch.
- Existing files at matching paths are updated; unrelated repository files are preserved.
- Delete the selected repository with a clear yes/no confirmation; no manual repository-name typing is required.
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

## Quick-delete files and folders

1. Connect an account and select the repository and branch.
2. Click **Quick Delete File / Folder**.
3. RepoPilot loads an expandable file/folder tree from GitHub. Expand folders and select the item you want to remove.
4. Click **Delete selected** and approve the confirmation. No path typing is required.
5. The browser refreshes after deletion. Deleting a folder removes all its tracked contents from the selected branch in one commit.

The dialog also includes **Refresh** and an optional **Delete by path…** fallback. An empty repository is shown as empty rather than raising GitHub's no-commit 409 response. Git does not track empty directories. Deleting a folder does not erase its previous versions from Git history; it removes the current branch's reference to that folder's contents. Very large repositories whose recursive Git tree is truncated by GitHub are rejected safely rather than partially deleted.

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


## v6 usability updates

- Right-click editable fields and text areas for Cut, Copy, Paste and Select all.
- Keyboard shortcuts: Ctrl+C, Ctrl+X, Ctrl+V, Ctrl+A, Ctrl+Insert, Shift+Insert and Shift+Delete.
- Read-only activity logs allow Copy and Select all while blocking edits.
- Repository deletion no longer asks you to type the repository name. Select a repository, click **QUICK DELETE REPOSITORY**, then approve the warning confirmation.
- Permanent repository deletion still requires one confirmation click to prevent accidental loss.


## v7 quick-delete update

- Added a visual, expandable repository tree for quick file/folder deletion.
- Select a file or folder and approve one confirmation; no manual path entry is needed.
- Folder deletion removes all tracked contents in a single commit.
- Added refresh, empty-repository handling, and a path-entry fallback.


## v8 copyright and security hardening

- Added an **About / Copyright** panel in the launcher and each account workspace. It identifies the authors and opens their LinkedIn profiles.
- Added the requested copyright attribution to the launcher and package. See `COPYRIGHT.txt` and `LICENSE-PROPRIETARY.txt`.
- Added **Disconnect & Clear Session**. A successful login clears the masked token input; the token remains in memory only while connected. Closing a workspace or the app clears the UI's token reference. Python cannot guarantee secure zeroization of strings.
- The preferred Windows release builder now uses Nuitka native compilation. Keep this source ZIP private and distribute only the compiled EXE.
- Added `SECURITY.md` with limitations, recommended token practices, signing guidance, and release steps.

### Important copy-protection limitation
No client-side program can be guaranteed impossible to copy or reverse engineer once distributed. Nuitka compilation raises the effort required for casual inspection, while copyright terms and Authenticode signing provide legal notice and publisher/tamper verification. They do not technically prevent all duplication. Stronger license enforcement requires a licensing backend controlled by the authors; never embed its private signing key in the desktop app.

### Build options
- `BUILD-WINDOWS.bat` — preferred Nuitka native-compilation release. Requires Python 3.11+ and a C compiler (the script asks Nuitka to download MinGW64 when needed).
- `BUILD-WINDOWS-COMPATIBLE.bat` — PyInstaller compatibility build; easier to inspect and not the hardened release.

Authors: **Mst. Choity Akter** (https://www.linkedin.com/in/mst-choity-akter-572067316/) and **MD. Junayedul Islam Zarif** (https://www.linkedin.com/in/pentesterjunayed/).
