# RepoPilot security and release-hardening notes

## Credential handling

- GitHub Personal Access Tokens and OAuth access tokens are not written to the app's settings files.
- The token entry is cleared after a successful connection. A workspace can be disconnected to clear the app's token references.
- Closing a workspace or the main app clears the references held by the UI. Python cannot guarantee secure zeroization of strings or remove copies that may briefly exist in process memory or in-flight network requests.
- The OAuth Client ID is public configuration, not an access token. It may be stored in `github_oauth.json` beside the portable app.
- Each account workspace has an independent GitHub session. Background operations use the token associated with the workspace that initiated them and reject stale results after a disconnect/reconnect.

## Destructive actions

- File and folder deletion require selecting the target in the repository browser and approving a confirmation dialog.
- Permanent repository deletion requires a separate confirmation and the GitHub token must have the appropriate permission. Repository deletion is irreversible.
- Uploads and repository writes are initiated through visible controls and confirmation/editor workflows.
- Use fine-grained tokens restricted to the repositories and permissions required. Revoke tokens that are no longer needed.

## Copy-protection limitation

A program that runs on someone else's computer can be copied, patched, or reverse engineered by a sufficiently determined person. Compiling and obfuscating code can increase effort, but cannot make duplication technically impossible. A copyright notice describes ownership and permitted use; it does not physically prevent copying.

For stronger commercial control, use a server-side licensing service with signed, expiring device activations and keep licensing decisions and valuable proprietary logic on a server you control. Do not embed a license-signing private key, API secret, or master credential in the desktop executable. A desktop-only offline license check can be patched.

## Recommended release process

1. Keep the developer/source ZIP private. Share only `dist\RepoPilot.exe` with end users.
2. Build with `BUILD-WINDOWS.bat` (Nuitka). The first build may download a compiler and take several minutes.
3. Obtain an Authenticode code-signing certificate in the copyright holder's or organization's name and sign the final EXE. Signing helps users verify publisher identity and detect post-signing changes; it does not stop copying. Never share the certificate's private key or PFX password.
4. Publish SHA-256 checksums for each official release through a trusted channel.
5. Use narrowly scoped GitHub tokens and revoke credentials that are no longer needed.

## Network and file access

- GitHub API operations require an internet connection.
- Local upload operations read the folder or file explicitly selected by the user.
- The local browser enumerates mounted Windows drive letters for navigation. It does not execute arbitrary shell commands or modify Windows/system files.
