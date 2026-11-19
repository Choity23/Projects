import os
import base64
import threading
import queue
import json
import time
import sys
import webbrowser
import urllib.request
import urllib.error
import urllib.parse
import re
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from pathlib import Path

APP_NAME = 'RepoPilot'
APP_VERSION = '1.5.0'
COPYRIGHT_YEAR = '2026'
COPYRIGHT_HOLDERS = ('Mst. Choity Akter',)
COPYRIGHT_LINE = 'Copyright © 2026 Mst. Choity Akter. All rights reserved.'
AUTHOR_LINKS = (
    ('Mst. Choity Akter', 'https://www.linkedin.com/in/mst-choity-akter-572067316/'),
)
API = 'https://api.github.com'
GITHUB_DEVICE_CODE_URL = 'https://github.com/login/device/code'
GITHUB_OAUTH_TOKEN_URL = 'https://github.com/login/oauth/access_token'
GITHUB_FINE_GRAINED_TOKEN_URL = 'https://github.com/settings/personal-access-tokens/new'
GITHUB_CLASSIC_TOKEN_URL = 'https://github.com/settings/tokens/new?scopes=repo,delete_repo&description=RepoPilot'
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
OAUTH_CONFIG_PATH = APP_DIR / 'github_oauth.json'


def oauth_post(url, fields):
    # POST form data to GitHub OAuth device-flow endpoints.
    data = urllib.parse.urlencode(fields).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST', headers={
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'RepoPilot-Desktop'
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode('utf-8')).get('error_description', str(exc))
        except Exception:
            detail = str(exc)
        raise RuntimeError(f'GitHub sign-in failed: {detail}')


def load_oauth_client_id():
    try:
        if OAUTH_CONFIG_PATH.exists():
            data = json.loads(OAUTH_CONFIG_PATH.read_text(encoding='utf-8'))
            return str(data.get('client_id', '')).strip()
    except Exception:
        pass
    return ''


def save_oauth_client_id(client_id):
    OAUTH_CONFIG_PATH.write_text(
        json.dumps({'client_id': client_id}, indent=2), encoding='utf-8'
    )


def available_local_drives():
    """Return mounted drive roots. On Windows this includes fixed, removable,
    optical and mapped network drives reported by GetLogicalDrives()."""
    if os.name != 'nt':
        return [os.path.abspath(os.sep)]
    drives = []
    try:
        import ctypes
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for index in range(26):
            if mask & (1 << index):
                root = f'{chr(65 + index)}:\\'
                if os.path.isdir(root):
                    drives.append(root)
    except Exception:
        for index in range(26):
            root = f'{chr(65 + index)}:\\'
            if os.path.isdir(root):
                drives.append(root)
    return drives










def clean_repo_path(value, allow_empty=False):
    """Normalize a repository-relative path and reject unsafe path segments."""
    value = (value or '').strip().replace('\\', '/')
    if value.startswith('/') or (len(value) >= 2 and value[1] == ':' and value[0].isalpha()):
        raise RuntimeError('Repository paths must be relative paths inside the selected repository.')
    if not value:
        if allow_empty:
            return ''
        raise RuntimeError('Enter a folder or file path inside the repository.')
    value = value.strip('/')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise RuntimeError('Use a repository-relative path. Empty, . and .. path segments are not allowed.')
    return '/'.join(parts)


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, method, path, data=None):
        raw = None if data is None else json.dumps(data).encode('utf-8')
        req = urllib.request.Request(API + path, data=raw, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'RepoPilot-Desktop'
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                body = response.read()
                return json.loads(body.decode('utf-8')) if body else {}
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode('utf-8')).get('message', str(exc))
            except Exception:
                detail = str(exc)
            raise RuntimeError(f'GitHub API {exc.code}: {detail}')
        except Exception as exc:
            raise RuntimeError(str(exc))

    @staticmethod
    def is_api_error(exc, code):
        return f'GitHub API {code}:' in str(exc)

    def me(self):
        return self.request('GET', '/user')

    def repos(self):
        result, page = [], 1
        while True:
            batch = self.request('GET', f'/user/repos?per_page=100&sort=updated&page={page}')
            result.extend(batch)
            if len(batch) < 100:
                return result
            page += 1

    def delete_repo(self, owner, repo):
        return self.request('DELETE', f'/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}')

    def create_repo(self, name, description='', private=True, auto_init=True):
        """Create a repository for the authenticated personal account."""
        name = (name or '').strip()
        if not name:
            raise RuntimeError('Enter a repository name.')
        payload = {
            'name': name,
            'description': (description or '').strip(),
            'private': bool(private),
            'auto_init': bool(auto_init),
        }
        return self.request('POST', '/user/repos', payload)

    def repo_tree(self, owner, repo, branch):
        """Return the selected branch's complete tracked tree for the quick-delete browser."""
        owner_q, repo_q = self._repo_parts(owner, repo)
        branch_q = urllib.parse.quote(branch, safe='')
        try:
            ref = self.request('GET', f'/repos/{owner_q}/{repo_q}/git/ref/heads/{branch_q}')
        except RuntimeError as exc:
            # An empty repository has no branch ref or commit yet. Show an empty
            # browser instead of surfacing GitHub's 409 response to the user.
            if self.is_api_error(exc, 404) or self.is_api_error(exc, 409):
                meta = self.request('GET', f'/repos/{owner_q}/{repo_q}')
                if int(meta.get('size') or 0) == 0:
                    return []
            raise
        commit = self.request(
            'GET', f'/repos/{owner_q}/{repo_q}/git/commits/{ref["object"]["sha"]}'
        )
        tree = self.request(
            'GET', f'/repos/{owner_q}/{repo_q}/git/trees/{commit["tree"]["sha"]}?recursive=1'
        )
        if tree.get('truncated'):
            raise RuntimeError(
                'GitHub returned a truncated repository tree. The quick-delete browser '
                'cannot safely show every item in this repository.'
            )
        return tree.get('tree', [])

    def _repo_parts(self, owner, repo):
        return urllib.parse.quote(owner, safe=''), urllib.parse.quote(repo, safe='')

    def write_content(self, owner, repo, path, content, branch, message):
        """Create/update one file, including bootstrapping a completely empty repo."""
        path = clean_repo_path(path)
        owner_q, repo_q = self._repo_parts(owner, repo)
        meta = self.request('GET', f'/repos/{owner_q}/{repo_q}')
        default_branch = meta.get('default_branch') or 'main'
        target_branch = (branch or default_branch).strip()
        if not target_branch:
            target_branch = default_branch

        ref_path = f'/repos/{owner_q}/{repo_q}/git/ref/heads/{urllib.parse.quote(target_branch, safe="")}'
        branch_exists = True
        try:
            self.request('GET', ref_path)
        except RuntimeError as exc:
            if self.is_api_error(exc, 404) or self.is_api_error(exc, 409):
                branch_exists = False
            else:
                raise

        api_path = f'/repos/{owner_q}/{repo_q}/contents/{urllib.parse.quote(path, safe="/")}'
        payload = {
            'message': message,
            'content': base64.b64encode(content).decode('ascii')
        }

        if not branch_exists:
            if int(meta.get('size') or 0) != 0:
                raise RuntimeError(
                    f'The branch "{target_branch}" does not exist. Choose an existing branch or create it on GitHub first.'
                )
            # Contents API creates the initial commit on the repository's default branch.
            result = self.request('PUT', api_path, payload)
            if target_branch != default_branch:
                default_ref = self.request(
                    'GET', f'/repos/{owner_q}/{repo_q}/git/ref/heads/{urllib.parse.quote(default_branch, safe="")}'
                )
                try:
                    self.request('POST', f'/repos/{owner_q}/{repo_q}/git/refs', {
                        'ref': f'refs/heads/{target_branch}',
                        'sha': default_ref['object']['sha']
                    })
                except RuntimeError as exc:
                    if not self.is_api_error(exc, 422):
                        raise
            return result

        # If a file already exists, GitHub requires its current SHA for an update.
        try:
            existing = self.request('GET', api_path + '?ref=' + urllib.parse.quote(target_branch, safe=''))
            if isinstance(existing, dict) and existing.get('sha'):
                payload['sha'] = existing['sha']
        except RuntimeError as exc:
            if not self.is_api_error(exc, 404):
                raise

        payload['branch'] = target_branch
        return self.request('PUT', api_path, payload)

    def delete_path(self, owner, repo, path, branch):
        # Delete a tracked file or every tracked file inside a repository folder in one commit.
        path = clean_repo_path(path)
        owner_q, repo_q = self._repo_parts(owner, repo)
        branch_q = urllib.parse.quote(branch, safe='')
        ref = self.request('GET', f'/repos/{owner_q}/{repo_q}/git/ref/heads/{branch_q}')
        parent_sha = ref['object']['sha']
        parent = self.request('GET', f'/repos/{owner_q}/{repo_q}/git/commits/{parent_sha}')
        base_tree = parent['tree']['sha']
        tree = self.request('GET', f'/repos/{owner_q}/{repo_q}/git/trees/{base_tree}?recursive=1')
        if tree.get('truncated'):
            raise RuntimeError('GitHub returned a truncated repository tree. Use GitHub website to delete this path safely.')
        entries = tree.get('tree', [])
        exact = [item for item in entries if item.get('path') == path]
        if exact and exact[0].get('type') == 'tree':
            # Removing the directory entry removes its whole subtree in one tree update.
            matches = exact[:1]
            reported_count = sum(
                1 for item in entries
                if item.get('path') == path or item.get('path', '').startswith(path + '/')
            )
        else:
            matches = [
                item for item in entries
                if item.get('path') == path or item.get('path', '').startswith(path + '/')
            ]
            reported_count = len(matches)
        if not matches:
            raise RuntimeError(f'No tracked file or folder was found at "{path}" on branch "{branch}".')
        removals = [{
            'path': item['path'],
            'mode': item.get('mode', '100644'),
            'type': item.get('type', 'blob'),
            'sha': None
        } for item in matches]
        new_tree = self.request('POST', f'/repos/{owner_q}/{repo_q}/git/trees', {
            'base_tree': base_tree,
            'tree': removals
        })
        commit = self.request('POST', f'/repos/{owner_q}/{repo_q}/git/commits', {
            'message': f'Delete {path} with RepoPilot',
            'tree': new_tree['sha'],
            'parents': [parent_sha]
        })
        self.request('PATCH', f'/repos/{owner_q}/{repo_q}/git/refs/heads/{branch_q}', {
            'sha': commit['sha'], 'force': False
        })
        return {'deleted_count': reported_count, 'html_url': commit.get('html_url', '')}

    def create_folder(self, owner, repo, folder_path, branch):
        folder_path = clean_repo_path(folder_path)
        keep_path = folder_path + '/.gitkeep'
        return self.write_content(
            owner, repo, keep_path,
            b'This file keeps this folder in the Git repository.\n',
            branch, f'Create folder {folder_path}'
        )

    def create_file(self, owner, repo, file_path, content, branch):
        file_path = clean_repo_path(file_path)
        if len(content) > 100 * 1024 * 1024:
            raise RuntimeError('The file is larger than GitHub\'s 100 MB limit.')
        return self.write_content(owner, repo, file_path, content, branch, f'Create or update {file_path}')

    def upload_folder(self, folder, owner, repo, branch, progress, destination_path=''):
        folder = Path(folder)
        destination_path = clean_repo_path(destination_path, allow_empty=True)
        files = [p for p in folder.rglob('*') if p.is_file() and '.git' not in p.parts]
        if not files:
            raise RuntimeError('The selected folder contains no files.')
        if len(files) > 5000:
            raise RuntimeError('This version limits a single push to 5,000 files.')

        owner_q, repo_q = self._repo_parts(owner, repo)
        meta = self.request('GET', f'/repos/{owner_q}/{repo_q}')
        default_branch = meta.get('default_branch') or 'main'
        ref_path = f'/repos/{owner_q}/{repo_q}/git/ref/heads/{urllib.parse.quote(branch, safe="")}'
        try:
            ref = self.request('GET', ref_path)
        except RuntimeError as exc:
            if self.is_api_error(exc, 409) or (self.is_api_error(exc, 404) and int(meta.get('size') or 0) == 0):
                first = files[0]
                rel = first.relative_to(folder).as_posix()
                first_path = f'{destination_path}/{rel}' if destination_path else rel
                progress(0, len(files), 'Initializing empty repository…')
                self.request('PUT', f'/repos/{owner_q}/{repo_q}/contents/{urllib.parse.quote(first_path, safe="/")}', {
                    'message': 'Initialize repository with RepoPilot',
                    'content': base64.b64encode(first.read_bytes()).decode('ascii')
                })
                default_ref = self.request(
                    'GET', f'/repos/{owner_q}/{repo_q}/git/ref/heads/{urllib.parse.quote(default_branch, safe="")}'
                )
                if branch != default_branch:
                    try:
                        ref = self.request('GET', ref_path)
                    except RuntimeError as missing:
                        if not self.is_api_error(missing, 404):
                            raise
                        self.request('POST', f'/repos/{owner_q}/{repo_q}/git/refs', {
                            'ref': f'refs/heads/{branch}',
                            'sha': default_ref['object']['sha']
                        })
                        ref = self.request('GET', ref_path)
                else:
                    ref = default_ref
            else:
                raise RuntimeError(
                    'The selected branch does not exist. Choose an existing branch or initialize an empty repository.'
                ) from exc

        parent_sha = ref['object']['sha']
        parent = self.request('GET', f'/repos/{owner_q}/{repo_q}/git/commits/{parent_sha}')
        base_tree = parent['tree']['sha']
        tree_items = []
        for index, file_path in enumerate(files, 1):
            relative = file_path.relative_to(folder).as_posix()
            repo_file_path = f'{destination_path}/{relative}' if destination_path else relative
            size = file_path.stat().st_size
            if size > 100 * 1024 * 1024:
                raise RuntimeError(f'{relative} is over GitHub\'s 100 MB file limit.')
            blob = self.request('POST', f'/repos/{owner_q}/{repo_q}/git/blobs', {
                'content': base64.b64encode(file_path.read_bytes()).decode('ascii'),
                'encoding': 'base64'
            })
            tree_items.append({'path': repo_file_path, 'mode': '100644', 'type': 'blob', 'sha': blob['sha']})
            progress(index, len(files), repo_file_path)

        tree_payload = {'tree': tree_items}
        if base_tree:
            tree_payload['base_tree'] = base_tree
        tree = self.request('POST', f'/repos/{owner_q}/{repo_q}/git/trees', tree_payload)
        commit = self.request('POST', f'/repos/{owner_q}/{repo_q}/git/commits', {
            'message': f'Upload {len(files)} file(s) with RepoPilot',
            'tree': tree['sha'],
            'parents': [parent_sha]
        })
        self.request('PATCH', f'/repos/{owner_q}/{repo_q}/git/refs/heads/{urllib.parse.quote(branch, safe="")}', {
            'sha': commit['sha'], 'force': False
        })
        return len(files), commit['html_url']


class AccountWindow:
    def __init__(self, app, number):
        self.app, self.number = app, number
        self.win = tk.Toplevel(app.root)
        self.win.title(f'RepoPilot — Workspace {number}')
        self.win.geometry('980x820')
        self.win.minsize(420, 390)
        self.win.configure(bg=self.app.palette['bg'])
        self.token = None
        self.username = None
        self.session_generation = 0
        self.oauth_client_id = load_oauth_client_id()
        self.oauth_cancel = None
        self.device_dialog = None
        self.folder = tk.StringVar()
        self.repo = tk.StringVar()
        self.branch = tk.StringVar(value='main')
        self.repo_path = tk.StringVar()
        self.q = queue.Queue()
        self._build()
        self.app.register_window(self)
        self.win.protocol('WM_DELETE_WINDOW', self.close_workspace)
        self.win.after(120, self._poll)

    def clear_credentials(self):
        # Invalidate any authentication attempt that began before this clear.
        # Drop references; Python cannot guarantee secure zeroization of strings.
        self.session_generation += 1
        if self.oauth_cancel is not None:
            self.oauth_cancel.set()
        self.token = None
        self.username = None
        try:
            self.token_entry.delete(0, 'end')
        except (tk.TclError, AttributeError):
            pass
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def disconnect(self):
        self.clear_credentials()
        self.repo.set('')
        self.repo_path.set('')
        self.folder.set('')
        try:
            self.repo_combo.set('')
            self.repo_combo['values'] = ()
            self.user_label.config(text='●  Not connected', foreground=self.app.palette['muted'])
            self.status.config(text='Disconnected. The app has cleared its session token reference.')
            self.logline('Disconnected; local session token reference cleared.')
            self.oauth_button.config(state='normal')
        except tk.TclError:
            pass


    def close_workspace(self):
        self.clear_credentials()
        try:
            if self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
        try:
            self.app.windows.remove(self)
        except ValueError:
            pass


    def _build(self):
        shell = ttk.Frame(self.win, padding=10, style='App.TFrame')
        shell.pack(fill='both', expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(shell, highlightthickness=0, bg=self.app.palette['bg'], bd=0)
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')
        content = ttk.Frame(self.canvas, padding=(7, 5, 7, 14), style='App.TFrame')
        content_id = self.canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(content_id, width=event.width))

        def wheel(event):
            try:
                if event.widget.winfo_toplevel() is self.win:
                    self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
            except tk.TclError:
                pass
        # Bind at application level so scrolling works while the pointer is over
        # entries, buttons, or labels; each workspace scrolls only its own canvas.
        self.win.bind_all('<MouseWheel>', wheel, add='+')

        # Branded hero area keeps the app identity and theme control easy to find.
        header = ttk.Frame(content, style='Hero.TFrame', padding=(17, 14))
        header.pack(fill='x', pady=(0, 11))
        header_top = ttk.Frame(header, style='Hero.TFrame')
        header_top.pack(fill='x')
        title_area = ttk.Frame(header_top, style='Hero.TFrame')
        title_area.pack(fill='x', expand=True)
        ttk.Label(title_area, text='RepoPilot', style='HeroTitle.TLabel').pack(anchor='w')
        ttk.Label(
            title_area,
            text=f'GITHUB WORKSPACE  •  ACCOUNT WINDOW #{self.number}',
            style='HeroSubtitle.TLabel'
        ).pack(anchor='w', pady=(3, 0))
        theme_row = ttk.Frame(header, style='Hero.TFrame')
        theme_row.pack(fill='x', pady=(8, 0))
        self.theme_button = ttk.Button(
            theme_row, text=self.app.theme_button_text(), command=self.app.toggle_theme,
            style='Theme.TButton'
        )
        self.theme_button.pack(side='right')
        ttk.Button(
            theme_row, text='©  ABOUT / COPYRIGHT',
            command=lambda: self.app.show_about(self.win), style='Secondary.TButton'
        ).pack(side='right', padx=(0, 7))
        ttk.Label(
            header, text='Upload projects, create files, organize folders and manage repositories.',
            style='HeroSubtitle.TLabel', wraplength=760
        ).pack(anchor='w', pady=(8, 0))

        auth = ttk.LabelFrame(content, text='  01  ·  CONNECT YOUR GITHUB ACCOUNT  ', padding=12, style='Card.TLabelframe')
        auth.pack(fill='x', pady=5)
        tokenrow = ttk.Frame(auth, style='CardInner.TFrame')
        tokenrow.pack(fill='x')
        self.token_entry = ttk.Entry(tokenrow, show='•')
        self.token_entry.pack(fill='x', expand=True, ipady=2)
        ttk.Button(auth, text='🔗  CONNECT TOKEN', command=self.login, style='Accent.TButton').pack(fill='x', pady=(7, 0))

        auth_actions = ttk.Frame(auth, style='CardInner.TFrame')
        auth_actions.pack(fill='x', pady=(9, 0))
        ttk.Button(auth_actions, text='＋ Fine-grained token', command=self.generate_fine_token, style='Info.TButton').pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(auth_actions, text='＋ Classic token', command=self.generate_classic_token, style='Secondary.TButton').pack(side='left', fill='x', expand=True, padx=(4, 0))

        oauthrow = ttk.Frame(auth, style='CardInner.TFrame')
        oauthrow.pack(fill='x', pady=(10, 0))
        ttk.Label(oauthrow, text='OAuth App Client ID', style='Field.TLabel').pack(anchor='w', pady=(0, 4))
        self.oauth_client_entry = ttk.Entry(oauthrow)
        self.oauth_client_entry.pack(fill='x', ipady=2)
        if self.oauth_client_id:
            self.oauth_client_entry.insert(0, self.oauth_client_id)
        self.oauth_button = ttk.Button(oauthrow, text='◉  SIGN IN WITH GITHUB', command=self.start_github_signin, style='Success.TButton')
        self.oauth_button.pack(fill='x', pady=(7, 0))
        ttk.Button(
            auth, text='⏏  DISCONNECT & CLEAR SESSION', command=self.disconnect,
            style='Danger.TButton'
        ).pack(fill='x', pady=(8, 0))

        self.user_label = ttk.Label(auth, text='●  Not connected', style='Status.TLabel')
        self.user_label.pack(anchor='w', pady=(10, 0))
        ttk.Label(
            auth,
            text='Connect with a Personal Access Token or browser sign-in. Tokens stay in memory only. For uploads, grant Contents: Read and write. For Create Repository, grant Repository creation: Read and write (or Administration: Read and write) on a fine-grained token, or repo scope on a classic token. Repository deletion also needs Administration: Read and write (fine-grained) or delete_repo (classic). Browser sign-in requires an OAuth App Client ID with Device Flow enabled.',
            style='CardHint.TLabel', wraplength=780
        ).pack(anchor='w', pady=(5, 0))

        dest = ttk.LabelFrame(content, text='  02  ·  REPOSITORY & DESTINATION  ', padding=12, style='Card.TLabelframe')
        dest.pack(fill='x', pady=5)
        dest.columnconfigure(1, weight=1)
        ttk.Label(dest, text='Repository', style='Field.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 9), pady=5)
        ttk.Entry(dest, textvariable=self.repo).grid(row=0, column=1, sticky='ew', pady=5, ipady=2)
        ttk.Label(dest, text='Branch', style='Field.TLabel').grid(row=1, column=0, sticky='w', padx=(0, 9), pady=5)
        ttk.Entry(dest, textvariable=self.branch).grid(row=1, column=1, sticky='ew', pady=5, ipady=2)
        ttk.Label(dest, text='Upload destination', style='Field.TLabel').grid(row=2, column=0, sticky='w', padx=(0, 9), pady=5)
        ttk.Entry(dest, textvariable=self.repo_path).grid(row=2, column=1, sticky='ew', pady=5, ipady=2)
        ttk.Label(
            dest, text='Example: my game/assets  ·  Leave blank to upload to the repository root.',
            style='CardHint.TLabel', wraplength=680
        ).grid(row=3, column=1, sticky='w', pady=(0, 5))

        repo_row = ttk.Frame(dest, style='CardInner.TFrame')
        repo_row.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(7, 4))
        ttk.Label(repo_row, text='YOUR REPOSITORIES', style='SectionHint.TLabel').pack(side='left')
        ttk.Button(repo_row, text='↻  REFRESH', command=self.load_repos, style='Secondary.TButton').pack(side='right')
        self.repo_combo = ttk.Combobox(dest, state='readonly')
        self.repo_combo.grid(row=5, column=0, columnspan=2, sticky='ew', pady=4, ipady=2)
        self.repo_combo.bind('<<ComboboxSelected>>', self.pick_repo)

        create_repo_row = ttk.Frame(dest, style='CardInner.TFrame')
        create_repo_row.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(5, 2))
        ttk.Button(
            create_repo_row, text='＋  CREATE NEW GITHUB REPOSITORY',
            command=self.create_repository_dialog, style='Success.TButton'
        ).pack(fill='x')

        tools = ttk.Frame(dest, style='CardInner.TFrame')
        tools.grid(row=7, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        ttk.Label(tools, text='REPOSITORY TOOLS', style='SectionHint.TLabel').pack(anchor='w', pady=(0, 6))
        toolrow1 = ttk.Frame(tools, style='CardInner.TFrame')
        toolrow1.pack(fill='x')
        ttk.Button(toolrow1, text='📁  CREATE FOLDER', command=self.create_folder, style='Success.TButton').pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(toolrow1, text='＋  CREATE FILE', command=self.create_file_dialog, style='Info.TButton').pack(side='left', fill='x', expand=True, padx=(4, 0))
        toolrow2 = ttk.Frame(tools, style='CardInner.TFrame')
        toolrow2.pack(fill='x', pady=(7, 0))
        ttk.Button(toolrow2, text='⚡  QUICK DELETE FILE / FOLDER', style='Danger.TButton', command=self.open_quick_delete_browser).pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(toolrow2, text='⚠  QUICK DELETE REPOSITORY', style='Danger.TButton', command=self.delete_repo).pack(side='left', fill='x', expand=True, padx=(4, 0))

        src = ttk.LabelFrame(content, text='  03  ·  SELECT LOCAL PROJECT  ', padding=12, style='Card.TLabelframe')
        src.pack(fill='x', pady=5)
        folderrow = ttk.Frame(src, style='CardInner.TFrame')
        folderrow.pack(fill='x')
        ttk.Entry(folderrow, textvariable=self.folder).pack(side='left', fill='x', expand=True, padx=(0, 8), ipady=2)
        ttk.Button(folderrow, text='📂  BROWSE', command=self.browse, style='Secondary.TButton').pack(side='left')
        ttk.Label(
            src, text='The selected folder contents upload into the destination above. Matching files are updated; unrelated repository files are preserved.',
            style='CardHint.TLabel', wraplength=780
        ).pack(anchor='w', pady=(8, 0))

        logbox = ttk.LabelFrame(content, text='  ACTIVITY & UPLOAD LOG  ', padding=9, style='Card.TLabelframe')
        logbox.pack(fill='both', expand=True, pady=(8, 4))
        self.log = tk.Text(
            logbox, height=7, wrap='word', state='disabled', bg=self.app.palette['log_bg'],
            fg=self.app.palette['text'], insertbackground=self.app.palette['text'],
            selectbackground=self.app.palette['accent'], relief='flat',
            font=('Consolas', 9), padx=11, pady=9, highlightthickness=1,
            highlightbackground=self.app.palette['border'], highlightcolor=self.app.palette['accent']
        )
        self.log.pack(fill='both', expand=True)

        footer = ttk.Frame(shell, padding=(4, 9, 4, 2), style='App.TFrame')
        footer.grid(row=1, column=0, columnspan=2, sticky='ew')
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer, style='App.TFrame')
        buttons.pack(fill='x')
        self.push_btn = ttk.Button(buttons, text='⬆  PUSH PROJECT TO GITHUB', command=self.push, style='Accent.TButton')
        self.push_btn.pack(side='left', fill='x', expand=True, ipady=7)
        ttk.Button(buttons, text='↗  OPEN REPOSITORY', command=self.open_repo, style='Secondary.TButton').pack(side='left', padx=(8, 0))
        self.progress = ttk.Progressbar(footer, mode='determinate', style='Accent.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(8, 4))
        self.status = ttk.Label(footer, text='Ready. Connect an account to begin.', style='Status.TLabel', wraplength=780)
        self.status.pack(anchor='w')

    def logline(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text + '\n')
        self.log.see('end')
        self.log.configure(state='disabled')

    def run_bg(self, function):
        threading.Thread(target=function, daemon=True).start()

    def selected_repo(self):
        destination = self.repo.get().strip()
        if destination.count('/') != 1 or not all(destination.split('/')):
            raise RuntimeError('Select or enter a repository in owner/name format.')
        branch = self.branch.get().strip()
        if not branch:
            raise RuntimeError('Enter a branch name.')
        return destination.split('/'), branch

    def login(self):
        token = self.token_entry.get().strip()
        if not token:
            messagebox.showwarning('Token required', 'Paste a GitHub Personal Access Token first.', parent=self.win)
            return
        self.session_generation += 1
        generation = self.session_generation
        self.status.config(text='Verifying GitHub token and loading repositories…')

        def work():
            try:
                github = GitHub(token)
                me = github.me()
                repos = github.repos()
                self.q.put(('login', token, me, repos, generation))
            except Exception as exc:
                self.q.put(('login_error', str(exc), generation))
        self.run_bg(work)

    def generate_fine_token(self):
        messagebox.showinfo(
            'Generate a fine-grained GitHub token',
            'GitHub will open in your browser. Select the repositories RepoPilot should access and grant:\n\n'
            '• Contents: Read and write (for uploads and file editing)\n'
            '• Repository creation: Read and write (to create repositories)\n'
            '• Administration: Read and write (to delete repositories; it can also cover repository creation)\n\n'
            'Create the token, copy it, paste it into the token field, then click Connect token.',
            parent=self.win
        )
        webbrowser.open(GITHUB_FINE_GRAINED_TOKEN_URL)

    def generate_classic_token(self):
        messagebox.showinfo(
            'Generate a classic GitHub token',
            'GitHub will open the classic token page with repo and delete_repo scopes selected. '
            'Classic tokens have broad repository access. Create the token, copy it, paste it into '
            'the token field, then click Connect token.',
            parent=self.win
        )
        webbrowser.open(GITHUB_CLASSIC_TOKEN_URL)

    def start_github_signin(self):
        client_id = self.oauth_client_entry.get().strip()
        if not client_id:
            messagebox.showwarning(
                'OAuth App Client ID required',
                'Browser sign-in needs a GitHub OAuth App Client ID with Device Flow enabled. '
                'The app publisher must register an OAuth App and provide its Client ID. '
                'You can use Generate fine-grained token or Generate classic token in the meantime.',
                parent=self.win
            )
            return
        try:
            save_oauth_client_id(client_id)
        except Exception as exc:
            messagebox.showerror('Could not save OAuth Client ID', str(exc), parent=self.win)
            return
        if self.oauth_cancel is not None:
            self.oauth_cancel.set()
        self.session_generation += 1
        self.oauth_cancel = threading.Event()
        cancel_event = self.oauth_cancel
        generation = self.session_generation
        self.oauth_button.config(state='disabled')
        self.status.config(text='Starting secure GitHub browser sign-in…')

        def work():
            try:
                device = oauth_post(GITHUB_DEVICE_CODE_URL, {
                    'client_id': client_id,
                    'scope': 'repo delete_repo'
                })
                if device.get('error'):
                    raise RuntimeError(device.get('error_description') or device['error'])
                user_code = device['user_code']
                device_code = device['device_code']
                verification_uri = device.get('verification_uri', 'https://github.com/login/device')
                expires_in = int(device.get('expires_in', 900))
                interval = max(1, int(device.get('interval', 5)))
                self.q.put(('device_code', user_code, verification_uri, expires_in))
                deadline = time.monotonic() + expires_in
                while time.monotonic() < deadline and not cancel_event.is_set():
                    time.sleep(interval)
                    if cancel_event.is_set():
                        return
                    token_data = oauth_post(GITHUB_OAUTH_TOKEN_URL, {
                        'client_id': client_id,
                        'device_code': device_code,
                        'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
                    })
                    if token_data.get('access_token'):
                        token = token_data['access_token']
                        github = GitHub(token)
                        me = github.me()
                        repos = github.repos()
                        self.q.put(('login', token, me, repos, generation))
                        return
                    error = token_data.get('error')
                    if error == 'authorization_pending':
                        continue
                    if error == 'slow_down':
                        interval += 5
                        continue
                    if error == 'access_denied':
                        raise RuntimeError('GitHub sign-in was denied in the browser.')
                    if error == 'expired_token':
                        raise RuntimeError('The GitHub device code expired. Start sign-in again.')
                    if error:
                        raise RuntimeError(token_data.get('error_description') or error)
                if not cancel_event.is_set():
                    raise RuntimeError('The GitHub device code expired. Start sign-in again.')
            except Exception as exc:
                if not cancel_event.is_set():
                    self.q.put(('oauth_error', str(exc), generation))
        self.run_bg(work)

    def show_device_code(self, user_code, verification_uri, expires_in):
        if self.device_dialog and self.device_dialog.winfo_exists():
            self.device_dialog.destroy()
        dialog = tk.Toplevel(self.win)
        self.device_dialog = dialog
        dialog.title('Complete GitHub sign-in')
        dialog.geometry('440x290')
        dialog.configure(bg=self.app.palette['bg'])
        dialog.minsize(380, 230)
        dialog.transient(self.win)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Finish signing in on GitHub', font=('Segoe UI', 15, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Open the link below and enter this one-time code:', wraplength=390).pack(anchor='w', pady=(10, 5))
        code = ttk.Label(frame, text=user_code, font=('Consolas', 22, 'bold'), foreground=self.app.palette['accent'], background=self.app.palette['bg'])
        code.pack(anchor='center', pady=7)
        ttk.Label(frame, text=verification_uri, foreground=self.app.palette['info'], background=self.app.palette['bg']).pack(anchor='center')
        ttk.Label(frame, text=f'This code expires in about {max(1, expires_in // 60)} minutes. RepoPilot will connect automatically after approval.', wraplength=390).pack(anchor='w', pady=(10, 10))
        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Button(row, text='Open GitHub', command=lambda: webbrowser.open(verification_uri)).pack(side='left')
        ttk.Button(row, text='Copy code', command=lambda: self.copy_device_code(user_code)).pack(side='left', padx=7)
        ttk.Button(row, text='Cancel sign-in', command=self.cancel_github_signin).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW', self.cancel_github_signin)

    def copy_device_code(self, code):
        self.win.clipboard_clear()
        self.win.clipboard_append(code)
        self.status.config(text='GitHub device code copied to clipboard.')

    def cancel_github_signin(self):
        if self.oauth_cancel is not None:
            self.oauth_cancel.set()
        if self.device_dialog and self.device_dialog.winfo_exists():
            self.device_dialog.destroy()
        self.oauth_button.config(state='normal')
        self.status.config(text='GitHub sign-in cancelled.')

    def load_repos(self):
        if not self.token:
            messagebox.showinfo('Connect first', 'Verify your token first.', parent=self.win)
            return
        self.status.config(text='Loading repositories…')
        token_snapshot = self.token
        generation = self.session_generation

        def work():
            try:
                repos = GitHub(token_snapshot).repos()
                self.q.put(('repos', repos, generation))
            except Exception as exc:
                self.q.put(('repos_error', str(exc), generation))
        self.run_bg(work)

    def pick_repo(self, _event=None):
        value = self.repo_combo.get()
        if value:
            self.repo.set(value)

    def browse(self):
        """Show a local file browser that lists both folders and files."""
        start = self.folder.get().strip()
        if not start or not os.path.isdir(start):
            start = str(Path.home())
        start = os.path.abspath(os.path.expanduser(start))

        dialog = tk.Toplevel(self.win)
        dialog.title('Browse local files and folders')
        dialog.configure(bg=self.app.palette['bg'])
        dialog.transient(self.win)
        dialog.resizable(True, True)
        dialog.geometry('760x560')
        dialog.minsize(480, 360)

        outer = ttk.Frame(dialog, padding=14, style='App.TFrame')
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        ttk.Label(outer, text='Choose a local project folder', style='HeroTitle.TLabel').grid(
            row=0, column=0, sticky='w'
        )
        ttk.Label(
            outer,
            text='Use the DRIVE dropdown to switch between mounted drives such as C: and D:. Folders and files are shown; open a folder to browse inside it, then select the folder to upload.',
            style='Hint.TLabel', wraplength=700
        ).grid(row=1, column=0, sticky='w', pady=(4, 10))

        current_path = tk.StringVar(value=start)
        drive_roots = available_local_drives()
        if not drive_roots:
            drive_roots = [os.path.abspath(os.sep)]
        drive_var = tk.StringVar()
        path_row = ttk.Frame(outer, style='App.TFrame')
        path_row.grid(row=2, column=0, sticky='new', pady=(0, 8))
        path_row.columnconfigure(2, weight=1)
        ttk.Label(path_row, text='DRIVE', style='Field.TLabel').grid(row=0, column=0, sticky='w', padx=(0, 5))
        drive_combo = ttk.Combobox(
            path_row, textvariable=drive_var, values=drive_roots,
            state='readonly', width=7
        )
        drive_combo.grid(row=0, column=1, sticky='w', padx=(0, 7))
        path_entry = ttk.Entry(path_row, textvariable=current_path)
        path_entry.grid(row=0, column=2, sticky='ew', padx=(0, 6))
        status = ttk.Label(outer, text='', style='Status.TLabel')
        status.grid(row=4, column=0, sticky='ew', pady=(7, 0))

        list_wrap = ttk.Frame(outer, style='CardInner.TFrame')
        list_wrap.grid(row=3, column=0, sticky='nsew')
        list_wrap.rowconfigure(0, weight=1)
        list_wrap.columnconfigure(0, weight=1)
        tree = ttk.Treeview(
            list_wrap, columns=('kind', 'size'), show='tree headings',
            selectmode='browse'
        )
        tree.heading('#0', text='Name')
        tree.heading('kind', text='Type')
        tree.heading('size', text='Size')
        tree.column('#0', width=390, minwidth=150, stretch=True)
        tree.column('kind', width=100, minwidth=75, stretch=False, anchor='w')
        tree.column('size', width=100, minwidth=75, stretch=False, anchor='e')
        ybar = ttk.Scrollbar(list_wrap, orient='vertical', command=tree.yview)
        xbar = ttk.Scrollbar(list_wrap, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        tree.grid(row=0, column=0, sticky='nsew')
        ybar.grid(row=0, column=1, sticky='ns')
        xbar.grid(row=1, column=0, sticky='ew')

        def human_size(size):
            value = float(size)
            for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
                if value < 1024 or unit == 'TB':
                    return f'{int(value)} {unit}' if unit == 'B' else f'{value:.1f} {unit}'
                value /= 1024
            return f'{value:.1f} TB'

        def refresh_listing(*_args):
            folder = os.path.abspath(os.path.expanduser(current_path.get().strip() or str(Path.home())))
            if not os.path.isdir(folder):
                status.config(text='That location does not exist or is not a folder.')
                return
            current_path.set(folder)
            if os.name == 'nt':
                drive, _tail = os.path.splitdrive(folder)
                selected_drive = drive + os.sep if drive else ''
            else:
                selected_drive = os.path.abspath(os.sep)
            if selected_drive in drive_roots:
                drive_var.set(selected_drive)
            for item in tree.get_children(''):
                tree.delete(item)
            directories, files = [], []
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=True):
                                directories.append(entry)
                            elif entry.is_file(follow_symlinks=True):
                                files.append(entry)
                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError) as exc:
                status.config(text=f'Cannot read this folder: {exc}')
                return
            directories.sort(key=lambda item: item.name.casefold())
            files.sort(key=lambda item: item.name.casefold())
            for entry in directories:
                tree.insert('', 'end', iid=f'd_{len(tree.get_children())}', text=f'📁  {entry.name}',
                            values=('Folder', '—'), tags=('folder',))
            for entry in files:
                try:
                    size = human_size(entry.stat(follow_symlinks=True).st_size)
                except OSError:
                    size = '—'
                tree.insert('', 'end', iid=f'f_{len(tree.get_children())}', text=f'📄  {entry.name}',
                            values=('File', size), tags=('file',))
            status.config(text=f'{len(directories)} folder(s) and {len(files)} file(s) in {folder}')

        def go_drive(_event=None):
            target = drive_var.get().strip()
            if target and os.path.isdir(target):
                current_path.set(target)
                refresh_listing()

        def selected_folder_path():
            selection = tree.selection()
            if not selection:
                return None
            item = selection[0]
            values = tree.item(item, 'values')
            if not values or values[0] != 'Folder':
                return None
            name = tree.item(item, 'text')
            if name.startswith('📁  '):
                name = name[3:].strip()
            return os.path.join(current_path.get(), name)

        def open_selected_folder(_event=None):
            target = selected_folder_path()
            if not target:
                status.config(text='Select a folder to open. Files are displayed but cannot be opened as folders.')
                return
            current_path.set(target)
            refresh_listing()

        def select_current_folder():
            folder = os.path.abspath(os.path.expanduser(current_path.get().strip()))
            if not os.path.isdir(folder):
                messagebox.showwarning('Invalid folder', 'Choose an existing folder.', parent=dialog)
                return
            self.folder.set(folder)
            dialog.destroy()

        def select_highlighted_folder():
            target = selected_folder_path()
            if not target:
                messagebox.showinfo('Select a folder', 'Highlight a folder row first. Files cannot be selected as upload folders.', parent=dialog)
                return
            self.folder.set(os.path.abspath(target))
            dialog.destroy()

        def go_up():
            folder = os.path.abspath(os.path.expanduser(current_path.get().strip()))
            parent = os.path.dirname(folder)
            if parent and parent != folder:
                current_path.set(parent)
                refresh_listing()

        toolbar = ttk.Frame(path_row, style='App.TFrame')
        toolbar.grid(row=0, column=3, sticky='e')
        ttk.Button(toolbar, text='↑ UP', command=go_up, style='Secondary.TButton').pack(side='left', padx=(0, 4))
        ttk.Button(toolbar, text='↻ REFRESH', command=refresh_listing, style='Secondary.TButton').pack(side='left')
        drive_combo.bind('<<ComboboxSelected>>', go_drive)
        path_entry.bind('<Return>', refresh_listing)
        tree.bind('<Double-1>', open_selected_folder)
        tree.bind('<Return>', open_selected_folder)

        actions = ttk.Frame(outer, style='App.TFrame')
        actions.grid(row=5, column=0, sticky='ew', pady=(10, 0))
        ttk.Button(actions, text='OPEN SELECTED FOLDER', command=open_selected_folder,
                   style='Info.TButton').pack(side='left')
        ttk.Button(actions, text='SELECT HIGHLIGHTED FOLDER', command=select_highlighted_folder,
                   style='Secondary.TButton').pack(side='left', padx=(7, 0))
        ttk.Button(actions, text='SELECT CURRENT FOLDER', command=select_current_folder,
                   style='Accent.TButton').pack(side='right')
        refresh_listing()
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.bind('<Control-l>', lambda _event: (path_entry.focus_set(), path_entry.selection_range(0, 'end')))
        path_entry.focus_set()

    def push(self):
        if not self.token:
            messagebox.showwarning('Not connected', 'Verify a GitHub token first.', parent=self.win)
            return False
        try:
            (owner, repo), branch = self.selected_repo()
            destination_path = clean_repo_path(self.repo_path.get(), allow_empty=True)
        except RuntimeError as exc:
            messagebox.showwarning('Destination needed', str(exc), parent=self.win)
            return False
        folder = self.folder.get().strip()
        if not os.path.isdir(folder):
            messagebox.showwarning('Folder needed', 'Choose a valid local project folder.', parent=self.win)
            return False
        target = f'{owner}/{repo}' + (f'/{destination_path}' if destination_path else '')
        if not messagebox.askyesno(
            'Confirm upload',
            f'Upload all files from:\n{folder}\n\nTo: {target}\nBranch: {branch}',
            parent=self.win
        ):
            return False
        self.push_btn.config(state='disabled')
        self.progress['value'] = 0
        self.status.config(text='Preparing upload…')
        token_snapshot = self.token
        generation = self.session_generation

        def work():
            try:
                if not token_snapshot or generation != self.session_generation:
                    raise RuntimeError('The connected GitHub session changed. Reconnect and retry the upload.')
                def progress(index, total, name):
                    self.q.put(('progress', index, total, name, generation))
                result = GitHub(token_snapshot).upload_folder(
                    folder, owner, repo, branch, progress, destination_path
                )
                self.q.put(('done', result, generation))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)
        return True


    def create_folder(self):
        if not self.token:
            messagebox.showwarning('Connect first', 'Verify your GitHub token first.', parent=self.win)
            return
        try:
            (owner, repo), branch = self.selected_repo()
        except RuntimeError as exc:
            messagebox.showwarning('Repository needed', str(exc), parent=self.win)
            return
        folder_path = simpledialog.askstring(
            'Create repository folder',
            'Folder path inside the repository (nested paths are supported):',
            initialvalue=self.repo_path.get().strip(),
            parent=self.win
        )
        if folder_path is None:
            return
        try:
            folder_path = clean_repo_path(folder_path)
        except RuntimeError as exc:
            messagebox.showwarning('Invalid folder path', str(exc), parent=self.win)
            return
        if not messagebox.askyesno(
            'Create folder',
            f'Create {owner}/{repo}/{folder_path}?\n\nGitHub uses a .gitkeep file to preserve an otherwise empty folder.',
            parent=self.win
        ):
            return
        self.status.config(text=f'Creating folder {folder_path}…')

        def work():
            try:
                result = GitHub(self.token).create_folder(owner, repo, folder_path, branch)
                self.q.put(('repo_action_done', f'Folder created: {folder_path}', result.get('content', {}).get('html_url', '')))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)

    def create_file_dialog(self, initial_path=None):
        if not self.token:
            messagebox.showwarning('Connect first', 'Verify your GitHub token first.', parent=self.win)
            return
        try:
            (owner, repo), branch = self.selected_repo()
        except RuntimeError as exc:
            messagebox.showwarning('Repository needed', str(exc), parent=self.win)
            return

        dialog = tk.Toplevel(self.win)
        dialog.title('Create file in GitHub repository')
        dialog.configure(bg=self.app.palette['bg'])
        dialog.transient(self.win)
        dialog.resizable(True, True)
        screen_w, screen_h = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
        width, height = min(720, screen_w - 60), min(640, screen_h - 90)
        dialog.geometry(f'{width}x{height}')
        dialog.minsize(min(430, width), min(360, height))
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=16, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text='Create a repository file', style='HeroTitle.TLabel').grid(
            row=0, column=0, sticky='w'
        )
        ttk.Label(
            frame, text=f'{owner}/{repo}  ·  branch: {branch}', style='Hint.TLabel'
        ).grid(row=1, column=0, sticky='w', pady=(3, 10))
        ttk.Label(frame, text='File path (include folder names)', style='Field.TLabel').grid(
            row=2, column=0, sticky='w'
        )
        default_path = str(initial_path or '').strip()
        if not default_path:
            selected_folder = self.repo_path.get().strip()
            default_path = selected_folder.rstrip('/\\') + '/README.md' if selected_folder else 'README.md'
        path_var = tk.StringVar(value=default_path)
        path_entry = ttk.Entry(frame, textvariable=path_var)
        path_entry.grid(row=3, column=0, sticky='ew', pady=(4, 9))
        ttk.Label(frame, text='File contents', style='Field.TLabel').grid(
            row=4, column=0, sticky='w'
        )

        editor_wrap = ttk.Frame(frame, style='App.TFrame')
        editor_wrap.grid(row=5, column=0, sticky='nsew', pady=(4, 10))
        editor_wrap.rowconfigure(0, weight=1)
        editor_wrap.columnconfigure(0, weight=1)
        editor = tk.Text(
            editor_wrap, wrap='none', font=('Consolas', 10), undo=True, padx=9, pady=8,
            bg=self.app.palette['input'], fg=self.app.palette['text'],
            insertbackground=self.app.palette['text'],
            selectbackground=self.app.palette['selection'], relief='flat'
        )
        yscroll = ttk.Scrollbar(editor_wrap, orient='vertical', command=editor.yview)
        xscroll = ttk.Scrollbar(editor_wrap, orient='horizontal', command=editor.xview)
        editor.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        editor.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')

        # The action bar is a dedicated, non-shrinking grid row. It stays visible
        # on first open and when Windows display scaling or a small screen is used.
        actions = ttk.Frame(frame, style='App.TFrame')
        actions.grid(row=6, column=0, sticky='ew', pady=(2, 0))
        ttk.Button(actions, text='CANCEL', command=dialog.destroy,
                   style='Secondary.TButton').pack(side='right')

        def submit():
            try:
                file_path = clean_repo_path(path_var.get())
            except RuntimeError as exc:
                messagebox.showwarning('Invalid file path', str(exc), parent=dialog)
                path_entry.focus_set()
                return
            content = editor.get('1.0', 'end-1c').encode('utf-8')
            if not messagebox.askyesno(
                'Save file to GitHub',
                f'Create or update {owner}/{repo}/{file_path} on branch {branch}?',
                parent=dialog
            ):
                return
            dialog.destroy()
            self.status.config(text=f'Saving {file_path} to GitHub…')

            def work():
                try:
                    result = GitHub(self.token).create_file(owner, repo, file_path, content, branch)
                    self.q.put(('repo_action_done', f'File saved: {file_path}', result.get('content', {}).get('html_url', '')))
                except Exception as exc:
                    self.q.put(('error', str(exc)))
            self.run_bg(work)

        save_button = ttk.Button(
            actions, text='✓  SAVE FILE TO GITHUB', command=submit, style='Accent.TButton'
        )
        save_button.pack(side='right', padx=(0, 8), ipady=3)
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.bind('<Control-Return>', lambda _event: submit())
        dialog.after(80, lambda: (path_entry.focus_set(), path_entry.icursor('end')))

    def create_repository_dialog(self):
        if not self.token:
            messagebox.showwarning('Connect first', 'Connect your GitHub account before creating a repository.', parent=self.win)
            return

        dialog = tk.Toplevel(self.win)
        dialog.title('Create a GitHub repository')
        dialog.configure(bg=self.app.palette['bg'])
        dialog.transient(self.win)
        dialog.resizable(True, False)
        dialog.geometry('540x440')
        dialog.minsize(430, 390)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=18, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Create a new repository', style='HeroTitle.TLabel').pack(anchor='w')
        ttk.Label(
            frame, text='Create a repository in your connected personal GitHub account.',
            style='Hint.TLabel', wraplength=480
        ).pack(anchor='w', pady=(4, 14))

        ttk.Label(frame, text='Repository name', style='Field.TLabel').pack(anchor='w')
        name_var = tk.StringVar()
        name_entry = ttk.Entry(frame, textvariable=name_var)
        name_entry.pack(fill='x', pady=(4, 11), ipady=3)

        ttk.Label(frame, text='Description (optional)', style='Field.TLabel').pack(anchor='w')
        description_var = tk.StringVar()
        ttk.Entry(frame, textvariable=description_var).pack(fill='x', pady=(4, 11), ipady=3)

        private_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text='Private repository (recommended)', variable=private_var
        ).pack(anchor='w', pady=(2, 6))
        initialize_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frame, text='Initialize with a README file', variable=initialize_var
        ).pack(anchor='w', pady=(0, 12))

        note = ttk.Label(
            frame,
            text='A private repository is visible only to you and people you authorize. You can change its visibility later on GitHub.',
            style='CardHint.TLabel', wraplength=480
        )
        note.pack(anchor='w', pady=(0, 12))

        actions = ttk.Frame(frame, style='App.TFrame')
        actions.pack(fill='x', side='bottom')
        ttk.Button(actions, text='CANCEL', command=dialog.destroy,
                   style='Secondary.TButton').pack(side='right')

        def submit():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning('Repository name required', 'Enter a name for the new repository.', parent=dialog)
                name_entry.focus_set()
                return
            if any(char in name for char in ('/', '\\', ' ')):
                messagebox.showwarning(
                    'Invalid repository name',
                    'Use a GitHub repository name without spaces or slash characters. Hyphens and underscores are allowed.',
                    parent=dialog
                )
                name_entry.focus_set()
                return
            create_button.config(state='disabled')
            status.config(text='Creating repository on GitHub…')

            def work():
                try:
                    result = GitHub(self.token).create_repo(
                        name, description_var.get(), private_var.get(), initialize_var.get()
                    )
                    self.q.put(('repository_created', dialog, result))
                except Exception as exc:
                    self.q.put(('repository_create_error', dialog, create_button, status, str(exc)))
            self.run_bg(work)

        status = ttk.Label(frame, text='', style='Status.TLabel', wraplength=480)
        status.pack(anchor='w', pady=(0, 7))
        create_button = ttk.Button(
            actions, text='＋  CREATE REPOSITORY', command=submit, style='Success.TButton'
        )
        create_button.pack(side='right', padx=(0, 8), ipady=3)
        name_entry.focus_set()
        dialog.bind('<Escape>', lambda _event: dialog.destroy())
        dialog.bind('<Return>', lambda _event: submit())

    def open_quick_delete_browser(self):
        """Open a visual file/folder picker so users never need to type paths."""
        if not self.token:
            messagebox.showwarning('Connect first', 'Connect your GitHub account first.', parent=self.win)
            return
        try:
            (owner, repo), branch = self.selected_repo()
        except RuntimeError as exc:
            messagebox.showwarning('Select a repository', str(exc), parent=self.win)
            return

        dialog = tk.Toplevel(self.win)
        dialog.title('Quick delete — GitHub files & folders')
        dialog.geometry('780x590')
        dialog.minsize(520, 420)
        dialog.configure(bg=self.app.palette['bg'])
        dialog.transient(self.win)

        frame = ttk.Frame(dialog, padding=16, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        ttk.Label(
            frame, text='Select a file or folder to delete',
            font=('Segoe UI', 17, 'bold'), foreground=self.app.palette['text']
        ).pack(anchor='w')
        ttk.Label(
            frame, text=f'{owner}/{repo}   ·   branch: {branch}',
            foreground=self.app.palette['muted']
        ).pack(anchor='w', pady=(3, 10))
        ttk.Label(
            frame,
            text='Choose an item below and click Delete selected. Folder deletion removes all tracked contents in one commit.',
            wraplength=720, foreground=self.app.palette['muted']
        ).pack(anchor='w', pady=(0, 10))

        tree_wrap = ttk.Frame(frame, style='CardInner.TFrame')
        tree_wrap.pack(fill='both', expand=True)
        tree = ttk.Treeview(
            tree_wrap, columns=('path', 'kind'), show='tree headings',
            selectmode='browse'
        )
        tree.heading('#0', text='Repository contents', anchor='w')
        tree.heading('path', text='Repository path', anchor='w')
        tree.heading('kind', text='Type', anchor='center')
        tree.column('#0', width=210, minwidth=130, stretch=False)
        tree.column('path', width=390, minwidth=150, stretch=True)
        tree.column('kind', width=95, minwidth=75, stretch=False, anchor='center')
        tree.tag_configure('folder', foreground=self.app.palette['accent'])
        tree.tag_configure('file', foreground=self.app.palette['text'])
        tree.tag_configure('submodule', foreground=self.app.palette['info'])
        yscroll = ttk.Scrollbar(tree_wrap, orient='vertical', command=tree.yview)
        xscroll = ttk.Scrollbar(tree_wrap, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        tree_wrap.rowconfigure(0, weight=1)
        tree_wrap.columnconfigure(0, weight=1)

        status = ttk.Label(frame, text='Loading repository contents…', style='Status.TLabel')
        status.pack(anchor='w', pady=(9, 7))
        actions = ttk.Frame(frame, style='App.TFrame')
        actions.pack(fill='x')
        delete_button = ttk.Button(
            actions, text='⚡  DELETE SELECTED', style='Danger.TButton',
            command=lambda: self.quick_delete_selected(
                dialog, tree, status, delete_button, owner, repo, branch
            ), state='disabled'
        )
        delete_button.pack(side='left')

        def update_delete_button(_event=None):
            selected = tree.selection()
            if selected:
                selected_values = tree.item(selected[0], 'values')
                can_delete = bool(selected_values and selected_values[0] and selected_values[1] != 'Repository')
            else:
                can_delete = False
            delete_button.config(state='normal' if can_delete else 'disabled')

        tree.bind('<<TreeviewSelect>>', update_delete_button)
        ttk.Button(
            actions, text='↻  REFRESH', style='Secondary.TButton',
            command=lambda: self.request_quick_delete_tree(
                dialog, tree, status, delete_button, owner, repo, branch
            )
        ).pack(side='left', padx=(8, 0))
        ttk.Button(
            actions, text='Delete by path…', style='Secondary.TButton',
            command=self.delete_repo_path_dialog
        ).pack(side='left', padx=(8, 0))
        ttk.Button(actions, text='Close', command=dialog.destroy).pack(side='right')

        self.request_quick_delete_tree(dialog, tree, status, delete_button, owner, repo, branch)

    def request_quick_delete_tree(self, dialog, tree, status, delete_button, owner, repo, branch):
        try:
            if not dialog.winfo_exists():
                return
        except tk.TclError:
            return
        status.config(text='Loading files and folders from GitHub…')
        delete_button.config(state='disabled')

        def work():
            try:
                entries = GitHub(self.token).repo_tree(owner, repo, branch)
                self.q.put((
                    'quick_delete_tree_loaded', dialog, tree, status,
                    delete_button, owner, repo, entries
                ))
            except Exception as exc:
                self.q.put((
                    'quick_delete_tree_error', dialog, status,
                    delete_button, str(exc)
                ))
        self.run_bg(work)

    def populate_quick_delete_tree(self, tree, owner, repo, entries):
        """Render GitHub's flat recursive tree as an expandable folder hierarchy."""
        for child in tree.get_children(''):
            tree.delete(child)
        root_iid = 'repository_root'
        tree.insert(
            '', 'end', iid=root_iid, text=f'📦  {repo}',
            values=('', 'Repository'), open=True
        )
        folder_ids = {}
        next_id = [0]

        def ensure_folder(path):
            if not path:
                return root_iid
            if path in folder_ids:
                return folder_ids[path]
            parent_path = path.rpartition('/')[0]
            parent_iid = ensure_folder(parent_path)
            next_id[0] += 1
            iid = f'folder_{next_id[0]}'
            name = path.rsplit('/', 1)[-1]
            tree.insert(
                parent_iid, 'end', iid=iid, text=f'📁  {name}',
                values=(path, 'Folder'), tags=('folder',), open=True
            )
            folder_ids[path] = iid
            return iid

        # Create directory nodes first so files are inserted beneath their folders.
        for entry in sorted(entries, key=lambda item: item.get('path', '').casefold()):
            path = entry.get('path', '')
            if path and entry.get('type') == 'tree':
                ensure_folder(path)

        for entry in sorted(entries, key=lambda item: item.get('path', '').casefold()):
            path = entry.get('path', '')
            if not path or entry.get('type') == 'tree':
                continue
            parent_path, _, name = path.rpartition('/')
            parent_iid = ensure_folder(parent_path)
            next_id[0] += 1
            iid = f'entry_{next_id[0]}'
            kind = 'Submodule' if entry.get('type') == 'commit' else 'File'
            icon = '🔗' if kind == 'Submodule' else '📄'
            tag = 'submodule' if kind == 'Submodule' else 'file'
            tree.insert(
                parent_iid, 'end', iid=iid, text=f'{icon}  {name}',
                values=(path, kind), tags=(tag,)
            )

        if entries:
            tree.item(root_iid, open=True)
            tree.selection_remove(tree.selection())

    def quick_delete_selected(self, dialog, tree, status, delete_button, owner, repo, branch):
        selection = tree.selection()
        if not selection:
            messagebox.showinfo('Choose an item', 'Select a file or folder in the list first.', parent=dialog)
            return
        item = selection[0]
        values = tree.item(item, 'values')
        if not values or not values[0] or values[1] == 'Repository':
            messagebox.showinfo('Choose a file or folder', 'The repository root cannot be deleted here. Select a file or folder.', parent=dialog)
            return
        path, kind = values[0], values[1]
        is_folder = kind == 'Folder'
        description = 'folder and all its tracked contents' if is_folder else 'file'
        if not messagebox.askyesno(
            f'Quick delete {description}?',
            f'Delete this {description}?\n\n{owner}/{repo}/{path}\n\n'
            f'Branch: {branch}\n\nThis creates a Git commit. Previous versions remain in Git history, but the selected item will be removed from the current branch.',
            icon='warning', default='no', parent=dialog
        ):
            return

        delete_button.config(state='disabled')
        status.config(text=f'Deleting {path} from GitHub…')

        def work():
            try:
                result = GitHub(self.token).delete_path(owner, repo, path, branch)
                self.q.put((
                    'quick_delete_done', dialog, tree, status, delete_button,
                    owner, repo, branch, path, result
                ))
            except Exception as exc:
                self.q.put((
                    'quick_delete_error', dialog, status,
                    delete_button, str(exc)
                ))
        self.run_bg(work)

    def delete_repo_path_dialog(self):
        if not self.token:
            messagebox.showwarning('Connect first', 'Connect your GitHub account first.', parent=self.win)
            return
        try:
            (owner, repo), branch = self.selected_repo()
        except RuntimeError as exc:
            messagebox.showwarning('Select a repository', str(exc), parent=self.win)
            return
        path = simpledialog.askstring(
            'Delete repository file or folder',
            'Enter the repository-relative file or folder path. A folder deletion removes all tracked files inside it:',
            initialvalue=self.repo_path.get().strip(),
            parent=self.win
        )
        if path is None:
            return
        try:
            path = clean_repo_path(path)
        except RuntimeError as exc:
            messagebox.showwarning('Invalid repository path', str(exc), parent=self.win)
            return
        if not messagebox.askyesno(
            'Confirm file/folder deletion',
            f'Delete {owner}/{repo}/{path} from branch {branch}?\n\n'
            'If this is a folder, all tracked files inside it will be removed in one commit. '
            'The previous content remains in Git history, but the current branch will no longer contain it.',
            parent=self.win
        ):
            return
        self.status.config(text=f'Deleting {path} from GitHub…')

        def work():
            try:
                result = GitHub(self.token).delete_path(owner, repo, path, branch)
                self.q.put(('repo_path_deleted', path, result))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)

    def delete_repo(self):
        if not self.token:
            messagebox.showwarning('Connect first', 'Connect your GitHub account first.', parent=self.win)
            return
        try:
            (owner, repo), _branch = self.selected_repo()
        except RuntimeError as exc:
            messagebox.showwarning('Select a repository', str(exc), parent=self.win)
            return
        destination = f'{owner}/{repo}'
        # No manual repository-name typing: select the repository, click Delete,
        # then approve this concise safety confirmation.
        confirmed = messagebox.askyesno(
            'Delete repository permanently?',
            f'Are you sure you want to permanently delete {destination}?\n\n'
            'This removes the repository, files, issues, pull requests and Git history. '
            'This action cannot be undone.',
            icon='warning',
            default='no',
            parent=self.win
        )
        if not confirmed:
            return
        self.status.config(text=f'Deleting {destination}…')

        def work():
            try:
                GitHub(self.token).delete_repo(owner, repo)
                self.q.put(('deleted', destination))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)

    def open_repo(self):
        import webbrowser
        destination = self.repo.get().strip()
        if destination.count('/') == 1:
            webbrowser.open('https://github.com/' + destination)

    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                kind = item[0]
                if kind == 'device_code':
                    self.show_device_code(item[1], item[2], item[3])
                    self.status.config(text='Waiting for you to approve the sign-in in your browser…')
                elif kind == 'login':
                    if len(item) > 4 and item[4] != self.session_generation:
                        continue
                    self.oauth_button.config(state='normal')
                    if self.device_dialog and self.device_dialog.winfo_exists():
                        self.device_dialog.destroy()
                    self.token = item[1]
                    try:
                        self.token_entry.delete(0, 'end')
                    except tk.TclError:
                        pass
                    self.username = item[2].get('login')
                    self.user_label.config(text=f'●  Connected as @{self.username}', foreground=self.app.palette['success'])
                    self.status.config(text='Connected. Repositories loaded automatically.')
                    self.logline(f'Connected: @{self.username}')
                    self._show_repos(item[3])
                elif kind == 'repos':
                    if len(item) > 2 and item[2] != self.session_generation:
                        continue
                    self._show_repos(item[1])
                elif kind == 'repos_error':
                    if len(item) > 2 and item[2] != self.session_generation:
                        continue
                    self.status.config(text='Could not load repositories.')
                    self.logline('ERROR: ' + item[1])
                    messagebox.showerror('Repository refresh failed', item[1], parent=self.win)
                elif kind == 'repository_created':
                    _, dialog, result = item
                    full_name = result.get('full_name', '')
                    self.repo.set(full_name)
                    self.branch.set(result.get('default_branch') or 'main')
                    self.repo_path.set('')
                    try:
                        if dialog.winfo_exists():
                            dialog.destroy()
                    except tk.TclError:
                        pass
                    self.logline(f'Created repository: {full_name}')
                    self.status.config(text=f'Repository created: {full_name}')
                    self.load_repos()
                    messagebox.showinfo(
                        'Repository created',
                        f'{full_name} was created successfully.\n\n'
                        f'Visibility: {"Private" if result.get("private") else "Public"}\n'
                        f'Default branch: {result.get("default_branch") or "main"}',
                        parent=self.win
                    )
                elif kind == 'repository_create_error':
                    _, dialog, create_button, status, error = item
                    if 'GitHub API 403:' in error or 'Resource not accessible' in error:
                        error += (
                            '\n\nCheck your token permissions: fine-grained tokens need '
                            'Repository creation: Read and write (or Administration: Read and write); '
                            'classic tokens need the repo scope. Organization repositories may also '
                            'require organization approval.'
                        )
                    try:
                        if dialog.winfo_exists():
                            create_button.config(state='normal')
                            status.config(text='Could not create the repository.')
                            messagebox.showerror('Repository creation failed', error, parent=dialog)
                    except tk.TclError:
                        pass
                elif kind == 'deleted':
                    self.logline('Deleted repository: ' + item[1])
                    self.status.config(text='Repository deleted successfully.')
                    self.repo.set('')
                    self.repo_combo.set('')
                    self.load_repos()
                    messagebox.showinfo('Repository deleted', f'{item[1]} was permanently deleted.', parent=self.win)
                elif kind == 'quick_delete_tree_loaded':
                    _, dialog, tree, status, delete_button, owner, repo, entries = item
                    try:
                        if dialog.winfo_exists():
                            self.populate_quick_delete_tree(tree, owner, repo, entries)
                            if entries:
                                status.config(text=f'Loaded {len(entries)} tracked item(s). Select a file or folder to delete.')
                                delete_button.config(state='disabled')
                            else:
                                status.config(text='This repository branch is empty. There are no files or folders to delete.')
                                delete_button.config(state='disabled')
                    except tk.TclError:
                        pass
                elif kind == 'quick_delete_tree_error':
                    _, dialog, status, delete_button, error = item
                    try:
                        if dialog.winfo_exists():
                            status.config(text='Could not load repository contents.')
                            delete_button.config(state='disabled')
                            messagebox.showerror('Could not load repository', error, parent=dialog)
                    except tk.TclError:
                        pass
                elif kind == 'quick_delete_done':
                    _, dialog, tree, status, delete_button, owner, repo, branch, path, result = item
                    self.logline(f'Quick deleted {path} ({result.get("deleted_count", 0)} tracked item(s))')
                    self.status.config(text=f'Deleted {path} from {owner}/{repo}.')
                    current = self.repo_path.get().strip().strip('/')
                    if current == path or current.startswith(path + '/'):
                        self.repo_path.set('')
                    try:
                        if dialog.winfo_exists():
                            status.config(text=f'Deleted {path}. Refreshing repository contents…')
                            self.request_quick_delete_tree(dialog, tree, status, delete_button, owner, repo, branch)
                            messagebox.showinfo(
                                'Deleted successfully',
                                f'Deleted {path} and {result.get("deleted_count", 0)} tracked item(s).',
                                parent=dialog
                            )
                    except tk.TclError:
                        pass
                elif kind == 'quick_delete_error':
                    _, dialog, status, delete_button, error = item
                    try:
                        if dialog.winfo_exists():
                            status.config(text='Delete failed. Your repository was not changed.')
                            delete_button.config(state='normal')
                            messagebox.showerror('Could not delete item', error, parent=dialog)
                    except tk.TclError:
                        pass
                elif kind == 'repo_path_deleted':
                    _, path, result = item
                    self.logline(f'Deleted {path} ({result.get("deleted_count", 0)} tracked item(s))')
                    self.status.config(text=f'Deleted {path} from the selected branch.')
                    current = self.repo_path.get().strip().strip('/')
                    if current == path or current.startswith(path + '/'):
                        self.repo_path.set('')
                    messagebox.showinfo(
                        'GitHub path deleted',
                        f'Deleted {path} and {result.get("deleted_count", 0)} tracked item(s).' +
                        (f'\n\nCommit: {result.get("html_url")}' if result.get('html_url') else ''),
                        parent=self.win
                    )
                elif kind == 'repo_action_done':
                    _, description, url = item
                    self.logline(description + (f' — {url}' if url else ''))
                    self.status.config(text=description)
                    if description.startswith('Folder created: '):
                        self.repo_path.set(description.replace('Folder created: ', '', 1))
                    messagebox.showinfo('GitHub updated', description + (f'\n\n{url}' if url else ''), parent=self.win)
                elif kind == 'progress':
                    if len(item) > 4 and item[4] != self.session_generation:
                        continue
                    _, index, total, name = item[:4]
                    self.progress['maximum'] = total
                    self.progress['value'] = index
                    self.status.config(text=f'Uploading {index}/{total}: {name}')
                elif kind == 'done':
                    if len(item) > 2 and item[2] != self.session_generation:
                        self.push_btn.config(state='normal')
                        continue
                    count, url = item[1]
                    self.push_btn.config(state='normal')
                    self.status.config(text=f'Upload complete — {count} files.')
                    self.logline(f'Success: {count} files committed. {url}')
                    messagebox.showinfo('Upload complete', f'{count} files uploaded successfully.\n\n{url}', parent=self.win)
                elif kind == 'login_error':
                    _, error, generation = item
                    if generation != self.session_generation:
                        continue
                    self.oauth_button.config(state='normal')
                    self.status.config(text='GitHub connection failed.')
                    self.logline('LOGIN ERROR: ' + error)
                    messagebox.showerror('GitHub connection failed', error, parent=self.win)
                elif kind == 'oauth_error':
                    _, error, generation = item
                    if generation != self.session_generation:
                        continue
                    self.oauth_button.config(state='normal')
                    if self.device_dialog and self.device_dialog.winfo_exists():
                        self.device_dialog.destroy()
                    self.status.config(text='GitHub sign-in failed.')
                    self.logline('OAUTH ERROR: ' + error)
                    messagebox.showerror('GitHub sign-in failed', error, parent=self.win)
                elif kind == 'error':
                    self.push_btn.config(state='normal')
                    self.oauth_button.config(state='normal')
                    if self.device_dialog and self.device_dialog.winfo_exists():
                        self.device_dialog.destroy()
                    self.status.config(text='Operation failed.')
                    self.logline('ERROR: ' + item[1])
                    messagebox.showerror('RepoPilot error', item[1], parent=self.win)
        except queue.Empty:
            pass
        if self.win.winfo_exists():
            self.win.after(120, self._poll)


    def _show_repos(self, repos):
        names = [repo['full_name'] for repo in repos]
        self.repo_combo['values'] = names
        self.status.config(
            text=f'Loaded {len(names)} repositories.' if names else
            'No repositories found. Type owner/repository manually; empty repositories are supported.'
        )
        self.logline(f'Loaded {len(names)} repositories')
        if names and not self.repo.get().strip():
            self.repo_combo.current(0)
            self.repo.set(names[0])
        elif self.repo.get().strip() in names:
            self.repo_combo.set(self.repo.get())



class App:
    PALETTES = {
        'light': {
            'bg': '#F3F6FC', 'panel': '#FFFFFF', 'panel_alt': '#EAF0FA',
            'text': '#17243A', 'muted': '#65748B', 'border': '#D8E1EF',
            'accent': '#5B55E7', 'accent_hover': '#4942D0', 'accent_text': '#FFFFFF',
            'success': '#0E9F78', 'success_hover': '#087D5D',
            'info': '#1976D2', 'info_hover': '#145EA8',
            'danger': '#D93659', 'danger_hover': '#B82747', 'danger_bg': '#FFF0F3',
            'input': '#FFFFFF', 'log_bg': '#FBFCFF', 'hero': '#3730A3',
            'hero_text': '#FFFFFF', 'hero_muted': '#DAD9FF', 'selection': '#DCD9FF'
        },
        'dark': {
            'bg': '#0C1220', 'panel': '#141E30', 'panel_alt': '#202D44',
            'text': '#EAF0FF', 'muted': '#9BAAC2', 'border': '#2B3A54',
            'accent': '#8B80FF', 'accent_hover': '#A39AFF', 'accent_text': '#11152A',
            'success': '#1EBB91', 'success_hover': '#159B77',
            'info': '#398CEB', 'info_hover': '#2875CA',
            'danger': '#F05B7A', 'danger_hover': '#D94768', 'danger_bg': '#3A1D2B',
            'input': '#0F192A', 'log_bg': '#0A111E', 'hero': '#242052',
            'hero_text': '#F7F7FF', 'hero_muted': '#C6C3FF', 'selection': '#514B91'
        }
    }

    def __init__(self):
        self.root = tk.Tk()
        self.theme = 'light'
        self.palette = self.PALETTES[self.theme]
        self.windows = []
        self.count = 0
        self._style()
        # Explicit clipboard shortcuts and a Windows-style right-click menu are
        # installed app-wide, including dynamically-created editor/dialog fields.
        self.root.bind_all('<FocusIn>', self._clipboard_focus_in, add='+')
        self.root.bind_all('<Button-1>', self._clipboard_mouse_down, add='+')
        self.root.bind_all('<Button-3>', self._clipboard_context_menu, add='+')
        self.root.title('RepoPilot — GitHub Multi-Account Uploader')
        self.root.geometry('620x430')
        self.root.resizable(True, True)
        self.root.minsize(400, 330)

        frame = ttk.Frame(self.root, padding=20, style='App.TFrame')
        frame.pack(fill='both', expand=True)
        hero = ttk.Frame(frame, style='Hero.TFrame', padding=(18, 17))
        hero.pack(fill='x')
        top = ttk.Frame(hero, style='Hero.TFrame')
        top.pack(fill='x')
        title_area = ttk.Frame(top, style='Hero.TFrame')
        title_area.pack(side='left', fill='x', expand=True)
        ttk.Label(title_area, text='RepoPilot', style='HeroTitle.TLabel').pack(anchor='w')
        ttk.Label(title_area, text='GITHUB DESKTOP WORKSPACE', style='HeroSubtitle.TLabel').pack(anchor='w', pady=(3, 0))
        self.theme_button = ttk.Button(top, text=self.theme_button_text(), command=self.toggle_theme, style='Theme.TButton')
        self.theme_button.pack(side='right', padx=(8, 0), anchor='n')
        ttk.Button(
            top, text='©  ABOUT', command=lambda: self.show_about(self.root),
            style='Secondary.TButton'
        ).pack(side='right', padx=(0, 7), anchor='n')
        ttk.Label(
            hero, text='One portable app. Multiple GitHub accounts. Complete repository control.',
            style='HeroSubtitle.TLabel', wraplength=510
        ).pack(anchor='w', pady=(12, 0))

        ttk.Label(frame, text='START A WORKSPACE', style='SectionHint.TLabel').pack(anchor='w', pady=(17, 7))
        ttk.Button(
            frame, text='＋  OPEN NEW ACCOUNT / UPLOAD WINDOW', command=self.new_window,
            style='Accent.TButton'
        ).pack(fill='x', ipady=10)
        features = ttk.LabelFrame(frame, text='  WHAT YOU CAN DO  ', padding=12, style='Card.TLabelframe')
        features.pack(fill='x', pady=(14, 0))
        ttk.Label(
            features,
            text='●  Upload projects  ·  ●  Create files & folders  ·  ●  Delete repository content\n●  Connect with token or GitHub sign-in  ·  ●  Light/Dark themes',
            style='Body.TLabel', wraplength=520, justify='left'
        ).pack(anchor='w')
        ttk.Label(
            frame,
            text='Open multiple independent workspaces. Each window can connect to a different GitHub account.',
            style='Hint.TLabel', wraplength=530
        ).pack(anchor='w', pady=(12, 0))
        ttk.Label(
            frame, text=COPYRIGHT_LINE, style='Hint.TLabel', wraplength=550
        ).pack(anchor='w', pady=(10, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.close_app)

    def close_app(self):
        for window in list(self.windows):
            try:
                window.clear_credentials()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass


    def show_about(self, parent=None):
        parent = parent or self.root
        dialog = tk.Toplevel(parent)
        dialog.title('About RepoPilot')
        dialog.geometry('590x500')
        dialog.minsize(520, 450)
        dialog.configure(bg=self.palette['bg'])
        dialog.transient(parent)

        outer = ttk.Frame(dialog, padding=17, style='App.TFrame')
        outer.pack(fill='both', expand=True)
        hero = ttk.Frame(outer, padding=(16, 13), style='Hero.TFrame')
        hero.pack(fill='x')
        ttk.Label(hero, text='RepoPilot', style='HeroTitle.TLabel').pack(anchor='w')
        ttk.Label(
            hero, text=f'GITHUB DESKTOP WORKSPACE  ·  VERSION {APP_VERSION}',
            style='HeroSubtitle.TLabel'
        ).pack(anchor='w', pady=(3, 0))

        authors = ttk.LabelFrame(
            outer, text='  CREATED BY  ', padding=12, style='Card.TLabelframe'
        )
        authors.pack(fill='x', pady=(12, 9))
        for name, url in AUTHOR_LINKS:
            row = ttk.Frame(authors, style='CardInner.TFrame')
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=name, style='Field.TLabel').pack(anchor='w')
            link = tk.Label(
                row, text=url, bg=self.palette['panel'], fg=self.palette['info'],
                cursor='hand2', font=('Segoe UI', 9, 'underline'), anchor='w'
            )
            link.pack(anchor='w')
            link.bind('<Button-1>', lambda _event, target=url: webbrowser.open(target))

        notice = ttk.LabelFrame(
            outer, text='  COPYRIGHT & OWNERSHIP NOTICE  ', padding=11,
            style='Card.TLabelframe'
        )
        notice.pack(fill='x', pady=(0, 9))
        ttk.Label(
            notice,
            text=COPYRIGHT_LINE + '\n\nAll rights reserved. No permission to reproduce, redistribute, sell, or create derivative copies is granted except as permitted by applicable law or with prior written permission from the copyright holder.',
            style='CardHint.TLabel', wraplength=520, justify='left'
        ).pack(anchor='w')

        security = ttk.LabelFrame(
            outer, text='  SECURITY & COPY-PROTECTION NOTE  ', padding=11,
            style='Card.TLabelframe'
        )
        security.pack(fill='x')
        ttk.Label(
            security,
            text='GitHub access tokens are not saved to a settings file. They are held in app memory while connected and the session reference is cleared when you disconnect or close a workspace. Python cannot guarantee secure memory erasure. No client-side app can be made impossible to copy or reverse engineer after distribution; the compiled release, copyright notice, and code signing can deter misuse and help verify the publisher, but cannot guarantee copy prevention.',
            style='CardHint.TLabel', wraplength=520, justify='left'
        ).pack(anchor='w')

        ttk.Button(outer, text='CLOSE', command=dialog.destroy, style='Accent.TButton').pack(anchor='e', pady=(12, 0))

    @staticmethod
    def _is_clipboard_widget(widget):
        supported = (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text, tk.Spinbox, ttk.Spinbox)
        return isinstance(widget, supported)

    def _clipboard_focus_in(self, event):
        widget = getattr(event, 'widget', None)
        if self._is_clipboard_widget(widget):
            self._install_clipboard_shortcuts(widget)

    def _clipboard_mouse_down(self, event):
        # Some Tk/Windows focus transitions do not emit FocusIn until the
        # window is activated. Installing on the first click makes shortcuts
        # reliable even in newly-opened dialogs and account windows.
        widget = getattr(event, 'widget', None)
        if self._is_clipboard_widget(widget):
            self._install_clipboard_shortcuts(widget)

    def _install_clipboard_shortcuts(self, widget):
        if getattr(widget, '_repopilot_clipboard_shortcuts', False):
            return
        bindings = {
            '<Control-c>': 'copy',
            '<Control-x>': 'cut',
            '<Control-v>': 'paste',
            '<Control-a>': 'select_all',
            '<Control-Insert>': 'copy',
            '<Shift-Insert>': 'paste',
            '<Shift-Delete>': 'cut',
        }
        for sequence, action in bindings.items():
            widget.bind(
                sequence,
                lambda _event, target=widget, operation=action: self._clipboard_action(target, operation),
                add='+'
            )
        widget._repopilot_clipboard_shortcuts = True

    @staticmethod
    def _widget_is_editable(widget):
        try:
            state = str(widget.cget('state')).lower()
        except (tk.TclError, AttributeError):
            state = 'normal'
        return state not in ('disabled', 'readonly')

    @staticmethod
    def _widget_selection(widget):
        try:
            if isinstance(widget, tk.Text):
                ranges = widget.tag_ranges('sel')
                if len(ranges) >= 2:
                    return widget.get(ranges[0], ranges[1])
                return ''
            if widget.selection_present():
                first = int(widget.index('sel.first'))
                last = int(widget.index('sel.last'))
                return widget.get()[first:last]
        except (tk.TclError, AttributeError, ValueError):
            pass
        return ''

    @staticmethod
    def _clear_widget_selection(widget):
        if isinstance(widget, tk.Text):
            ranges = widget.tag_ranges('sel')
            if len(ranges) >= 2:
                widget.delete(ranges[0], ranges[1])
                return True
        else:
            try:
                if widget.selection_present():
                    widget.delete('sel.first', 'sel.last')
                    return True
            except (tk.TclError, AttributeError):
                pass
        return False

    def _clipboard_action(self, widget, action):
        try:
            if action == 'select_all':
                if isinstance(widget, tk.Text):
                    widget.tag_add('sel', '1.0', 'end-1c')
                    widget.mark_set('insert', 'end-1c')
                else:
                    widget.selection_range(0, 'end')
                    widget.icursor('end')
                return 'break'

            if action == 'copy':
                selected = self._widget_selection(widget)
                if selected:
                    widget.clipboard_clear()
                    widget.clipboard_append(selected)
                    widget.update_idletasks()
                return 'break'

            if action == 'cut':
                if not self._widget_is_editable(widget):
                    return 'break'
                selected = self._widget_selection(widget)
                if selected:
                    widget.clipboard_clear()
                    widget.clipboard_append(selected)
                    widget.update_idletasks()
                    self._clear_widget_selection(widget)
                return 'break'

            if action == 'paste':
                if not self._widget_is_editable(widget):
                    return 'break'
                pasted = widget.clipboard_get()
                self._clear_widget_selection(widget)
                if isinstance(widget, tk.Text):
                    widget.insert('insert', pasted)
                else:
                    widget.insert('insert', pasted)
                return 'break'
        except tk.TclError:
            # Empty clipboard, read-only widget, or unavailable OS clipboard.
            return 'break'
        return 'break'

    def _clipboard_context_menu(self, event):
        widget = getattr(event, 'widget', None)
        if not self._is_clipboard_widget(widget):
            return
        self._install_clipboard_shortcuts(widget)
        try:
            has_selection = bool(self._widget_selection(widget))
            widget.focus_set()
            # If no text is selected, place the insertion cursor where the user
            # right-clicked so Paste behaves naturally at the pointer location.
            if not has_selection:
                if isinstance(widget, tk.Text):
                    widget.mark_set('insert', widget.index(f'@{event.x},{event.y}'))
                else:
                    widget.icursor(widget.index(f'@{event.x}'))
            editable = self._widget_is_editable(widget)
            menu = tk.Menu(
                self.root, tearoff=0,
                background=self.palette['panel'], foreground=self.palette['text'],
                activebackground=self.palette['accent'], activeforeground='#FFFFFF',
                disabledforeground=self.palette['muted']
            )
            menu.add_command(label='Cut', accelerator='Ctrl+X',
                             command=lambda w=widget: self._clipboard_action(w, 'cut'),
                             state='normal' if editable and has_selection else 'disabled')
            menu.add_command(label='Copy', accelerator='Ctrl+C',
                             command=lambda w=widget: self._clipboard_action(w, 'copy'),
                             state='normal' if has_selection else 'disabled')
            menu.add_command(label='Paste', accelerator='Ctrl+V',
                             command=lambda w=widget: self._clipboard_action(w, 'paste'),
                             state='normal' if editable else 'disabled')
            menu.add_separator()
            menu.add_command(label='Select all', accelerator='Ctrl+A',
                             command=lambda w=widget: self._clipboard_action(w, 'select_all'))
            menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            pass
        finally:
            try:
                menu.grab_release()
            except (tk.TclError, UnboundLocalError):
                pass
        return 'break'

    def _style(self):
        self.style = ttk.Style(self.root)
        if 'clam' in self.style.theme_names():
            self.style.theme_use('clam')
        self.apply_theme()

    def theme_button_text(self):
        return '☾  DARK MODE' if self.theme == 'light' else '☀  LIGHT MODE'

    def update_theme_controls(self):
        label = self.theme_button_text()
        if hasattr(self, 'theme_button') and self.theme_button.winfo_exists():
            self.theme_button.configure(text=label)
        for window in list(self.windows):
            try:
                if window.win.winfo_exists() and hasattr(window, 'theme_button'):
                    window.theme_button.configure(text=label)
            except tk.TclError:
                pass

    def toggle_theme(self):
        self.theme = 'dark' if self.theme == 'light' else 'light'
        self.palette = self.PALETTES[self.theme]
        self.apply_theme()
        self.update_theme_controls()

    def register_window(self, window):
        self.windows.append(window)
        self.apply_theme_to_window(window)

    def apply_theme_to_window(self, window):
        p = self.palette
        try:
            if window.win.winfo_exists():
                window.win.configure(bg=p['bg'])
            if hasattr(window, 'canvas') and window.canvas.winfo_exists():
                window.canvas.configure(bg=p['bg'])
            if hasattr(window, 'log') and window.log.winfo_exists():
                window.log.configure(
                    bg=p['log_bg'], fg=p['text'], insertbackground=p['text'],
                    selectbackground=p['accent'], highlightbackground=p['border'],
                    highlightcolor=p['accent']
                )
            if hasattr(window, 'user_label') and window.user_label.winfo_exists():
                connected = bool(window.username)
                window.user_label.configure(foreground=p['success'] if connected else p['muted'])
        except tk.TclError:
            pass


    def apply_theme(self):
        p = self.palette
        self.root.configure(bg=p['bg'])
        st = self.style
        st.configure('.', font=('Segoe UI', 10), background=p['bg'], foreground=p['text'])
        st.configure('App.TFrame', background=p['bg'])
        st.configure('CardInner.TFrame', background=p['panel'])
        st.configure('Hero.TFrame', background=p['hero'])
        st.configure('TLabelframe', background=p['panel'], bordercolor=p['border'], relief='solid', borderwidth=1)
        st.configure('Card.TLabelframe', background=p['panel'], bordercolor=p['border'], relief='solid', borderwidth=1)
        st.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'), foreground=p['accent'], background=p['panel'])
        st.configure('Card.TLabelframe.Label', font=('Segoe UI', 10, 'bold'), foreground=p['accent'], background=p['panel'])
        st.configure('TLabel', background=p['bg'], foreground=p['text'])
        st.configure('Title.TLabel', background=p['bg'], foreground=p['text'], font=('Segoe UI', 25, 'bold'))
        st.configure('Subtitle.TLabel', background=p['bg'], foreground=p['muted'], font=('Segoe UI', 10))
        st.configure('Body.TLabel', background=p['panel'], foreground=p['text'], font=('Segoe UI', 10))
        st.configure('Hint.TLabel', background=p['bg'], foreground=p['muted'], font=('Segoe UI', 9))
        st.configure('CardHint.TLabel', background=p['panel'], foreground=p['muted'], font=('Segoe UI', 9))
        st.configure('Field.TLabel', background=p['panel'], foreground=p['text'], font=('Segoe UI', 9, 'bold'))
        st.configure('SectionHint.TLabel', background=p['panel'], foreground=p['accent'], font=('Segoe UI', 9, 'bold'))
        st.configure('Status.TLabel', background=p['bg'], foreground=p['muted'], font=('Segoe UI', 9, 'bold'))
        st.configure('HeroTitle.TLabel', background=p['hero'], foreground=p['hero_text'], font=('Segoe UI', 24, 'bold'))
        st.configure('HeroSubtitle.TLabel', background=p['hero'], foreground=p['hero_muted'], font=('Segoe UI', 9, 'bold'))

        st.configure('TButton', padding=(11, 8), background=p['panel_alt'], foreground=p['text'], borderwidth=0, focusthickness=2, focuscolor=p['accent'])
        st.map('TButton', background=[('active', p['border']), ('pressed', p['selection'])], foreground=[('disabled', p['muted'])])
        st.configure('Accent.TButton', padding=(13, 10), background=p['accent'], foreground=p['accent_text'], borderwidth=0, font=('Segoe UI', 10, 'bold'))
        st.map('Accent.TButton', background=[('active', p['accent_hover']), ('pressed', p['accent_hover'])], foreground=[('disabled', p['muted'])])
        st.configure('Secondary.TButton', padding=(10, 8), background=p['panel_alt'], foreground=p['text'], borderwidth=0, font=('Segoe UI', 9, 'bold'))
        st.map('Secondary.TButton', background=[('active', p['border']), ('pressed', p['selection'])])
        st.configure('Info.TButton', padding=(10, 8), background=p['info'], foreground='#FFFFFF', borderwidth=0, font=('Segoe UI', 9, 'bold'))
        st.map('Info.TButton', background=[('active', p['info_hover']), ('pressed', p['info_hover'])])
        st.configure('Success.TButton', padding=(10, 8), background=p['success'], foreground='#FFFFFF', borderwidth=0, font=('Segoe UI', 9, 'bold'))
        st.map('Success.TButton', background=[('active', p['success_hover']), ('pressed', p['success_hover'])])
        st.configure('Danger.TButton', padding=(10, 8), background=p['danger_bg'], foreground=p['danger'], borderwidth=1, bordercolor=p['danger'], font=('Segoe UI', 9, 'bold'))
        st.map('Danger.TButton', background=[('active', p['danger']), ('pressed', p['danger_hover'])], foreground=[('active', '#FFFFFF'), ('pressed', '#FFFFFF')])
        st.configure('Theme.TButton', padding=(10, 8), background=p['panel_alt'], foreground=p['accent'], borderwidth=0, font=('Segoe UI', 9, 'bold'))
        st.map('Theme.TButton', background=[('active', p['border']), ('pressed', p['selection'])])

        st.configure('TEntry', padding=7, fieldbackground=p['input'], foreground=p['text'], insertcolor=p['text'], bordercolor=p['border'], lightcolor=p['border'], darkcolor=p['border'])
        st.map('TEntry', fieldbackground=[('disabled', p['panel_alt'])], foreground=[('disabled', p['muted'])])
        st.configure('TCombobox', padding=7, fieldbackground=p['input'], background=p['panel_alt'], foreground=p['text'], arrowcolor=p['accent'], bordercolor=p['border'])
        st.map('TCombobox', fieldbackground=[('readonly', p['input'])], foreground=[('readonly', p['text'])], selectbackground=[('readonly', p['accent'])], selectforeground=[('readonly', '#FFFFFF')])
        st.configure('Treeview', background=p['input'], fieldbackground=p['input'], foreground=p['text'], bordercolor=p['border'], rowheight=27)
        st.map('Treeview', background=[('selected', p['selection'])], foreground=[('selected', p['text'])])
        st.configure('Treeview.Heading', background=p['panel_alt'], foreground=p['text'], font=('Segoe UI', 9, 'bold'), relief='flat')
        st.map('Treeview.Heading', background=[('active', p['border'])])
        st.configure('TScrollbar', background=p['panel_alt'], troughcolor=p['bg'], bordercolor=p['bg'], arrowcolor=p['muted'])
        st.configure('Accent.Horizontal.TProgressbar', background=p['accent'], troughcolor=p['panel_alt'], bordercolor=p['border'], lightcolor=p['accent'], darkcolor=p['accent'])
        st.configure('TProgressbar', background=p['accent'], troughcolor=p['panel_alt'])

        for window in list(self.windows):
            self.apply_theme_to_window(window)

    def new_window(self):
        self.count += 1
        AccountWindow(self, self.count)

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
