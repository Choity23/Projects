# RepoPilot security and release-hardening notes

## What this release improves
- The preferred Windows release build uses Nuitka to compile the Python application into a native executable rather than shipping plain `.py` modules inside a PyInstaller bundle. This raises the effort required for casual source inspection; it is not unbreakable protection.
- The application does not write GitHub Personal Access Tokens or OAuth access tokens to its settings file. The token entry is cleared after a successful connection.
- A workspace can be disconnected to clear the app's token reference. Closing a workspace or the main app also clears the references held by the UI.
- The About dialog and package contain the requested copyright attribution and proprietary-use notice.
- OAuth Client ID is public configuration, not an access token. It may be stored in `github_oauth.json`.

## Important limitation: copy prevention is not absolute
A program that runs on someone else's computer can be copied, patched, or reverse engineered by a sufficiently determined person. Compiling and obfuscating code can increase effort, but cannot make duplication technically impossible. A copyright notice describes ownership and permitted use; it does not physically prevent copying.

For stronger commercial control, use a server-side licensing service with signed, expiring device activations and keep licensing decisions and valuable proprietary logic on a server you control. Do not embed a license-signing private key, API secret, or master credential in the desktop executable. A desktop-only offline license check can be patched.

## Recommended release process
1. Keep the developer/source ZIP private. Share only `dist\RepoPilot.exe` with end users.
2. Build with `BUILD-WINDOWS.bat` (Nuitka). The first build may download a compiler and take several minutes.
3. Obtain an Authenticode code-signing certificate in the authors' or organization’s name and sign the final EXE. Signing helps users verify publisher identity and detect post-signing changes; it does not stop copying. Never share the certificate's private key or PFX password.
4. Publish SHA-256 checksums for each official release through a trusted channel.
5. Use fine-grained GitHub tokens restricted to only the repositories and permissions required. Revoke tokens that are no longer needed.

## Token handling limits
Tokens are held in process memory while a GitHub workspace is connected. The app clears its references on disconnect and close, but Python strings cannot be reliably zeroized, and tokens may remain briefly in process memory or in-flight network requests. Use short-lived or narrowly scoped credentials where available.
