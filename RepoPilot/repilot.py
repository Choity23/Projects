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
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path

APP_NAME = 'RepoPilot'
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
        else:
            matches = [
                item for item in entries
                if item.get('path') == path or item.get('path', '').startswith(path + '/')
            ]
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
        return {'deleted_count': len(matches), 'html_url': commit.get('html_url', '')}

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
        self.win.after(120, self._poll)

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

        self.user_label = ttk.Label(auth, text='●  Not connected', style='Status.TLabel')
        self.user_label.pack(anchor='w', pady=(10, 0))
        ttk.Label(
            auth,
            text='Connect with a Personal Access Token or browser sign-in. Tokens stay in memory only. For token creation, grant Contents: Read and write; repository deletion also needs Administration: Read and write (fine-grained) or delete_repo (classic). Browser sign-in requires an OAuth App Client ID with Device Flow enabled.',
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

        tools = ttk.Frame(dest, style='CardInner.TFrame')
        tools.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        ttk.Label(tools, text='REPOSITORY TOOLS', style='SectionHint.TLabel').pack(anchor='w', pady=(0, 6))
        toolrow1 = ttk.Frame(tools, style='CardInner.TFrame')
        toolrow1.pack(fill='x')
        ttk.Button(toolrow1, text='📁  CREATE FOLDER', command=self.create_folder, style='Success.TButton').pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(toolrow1, text='＋  CREATE FILE', command=self.create_file_dialog, style='Info.TButton').pack(side='left', fill='x', expand=True, padx=(4, 0))
        toolrow2 = ttk.Frame(tools, style='CardInner.TFrame')
        toolrow2.pack(fill='x', pady=(7, 0))
        ttk.Button(toolrow2, text='⌫  DELETE FILE / FOLDER', style='Danger.TButton', command=self.delete_repo_path_dialog).pack(side='left', fill='x', expand=True, padx=(0, 4))
        ttk.Button(toolrow2, text='⚠  DELETE REPOSITORY', style='Danger.TButton', command=self.delete_repo).pack(side='left', fill='x', expand=True, padx=(4, 0))

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
        self.status.config(text='Verifying GitHub token and loading repositories…')

        def work():
            try:
                github = GitHub(token)
                me = github.me()
                repos = github.repos()
                self.q.put(('login', token, me, repos))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)

    def generate_fine_token(self):
        messagebox.showinfo(
            'Generate a fine-grained GitHub token',
            'GitHub will open in your browser. Select the repositories RepoPilot should access and grant:\n\n'
            '• Contents: Read and write\n'
            '• Administration: Read and write (only if you want to delete repositories)\n\n'
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
        self.oauth_cancel = threading.Event()
        cancel_event = self.oauth_cancel
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
                        self.q.put(('login', token, me, repos))
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
                    self.q.put(('error', str(exc)))
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

        def work():
            try:
                self.q.put(('repos', GitHub(self.token).repos()))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)

    def pick_repo(self, _event=None):
        value = self.repo_combo.get()
        if value:
            self.repo.set(value)

    def browse(self):
        selected = filedialog.askdirectory(parent=self.win)
        if selected:
            self.folder.set(selected)

    def push(self):
        if not self.token:
            messagebox.showwarning('Not connected', 'Verify a GitHub token first.', parent=self.win)
            return
        try:
            (owner, repo), branch = self.selected_repo()
            destination_path = clean_repo_path(self.repo_path.get(), allow_empty=True)
        except RuntimeError as exc:
            messagebox.showwarning('Destination needed', str(exc), parent=self.win)
            return
        folder = self.folder.get().strip()
        if not os.path.isdir(folder):
            messagebox.showwarning('Folder needed', 'Choose a valid local project folder.', parent=self.win)
            return
        target = f'{owner}/{repo}' + (f'/{destination_path}' if destination_path else '')
        if not messagebox.askyesno(
            'Confirm upload',
            f'Upload all files from:\n{folder}\n\nTo: {target}\nBranch: {branch}',
            parent=self.win
        ):
            return
        self.push_btn.config(state='disabled')
        self.progress['value'] = 0
        self.status.config(text='Preparing upload…')

        def work():
            try:
                def progress(index, total, name):
                    self.q.put(('progress', index, total, name))
                result = GitHub(self.token).upload_folder(
                    folder, owner, repo, branch, progress, destination_path
                )
                self.q.put(('done', result))
            except Exception as exc:
                self.q.put(('error', str(exc)))
        self.run_bg(work)

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

    def create_file_dialog(self):
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
        dialog.geometry('650x560')
        dialog.minsize(430, 380)
        dialog.configure(bg='#f3f6fc')
        dialog.transient(self.win)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Create a repository file', font=('Segoe UI', 16, 'bold'), foreground='#142d50').pack(anchor='w')
        ttk.Label(frame, text=f'{owner}/{repo}  ·  branch: {branch}', foreground='#64748b').pack(anchor='w', pady=(3, 12))
        ttk.Label(frame, text='File path (include folder names)').pack(anchor='w')
        initial_path = self.repo_path.get().strip()
        if initial_path:
            initial_path = initial_path.rstrip('/\\') + '/README.md'
        else:
            initial_path = 'README.md'
        path_var = tk.StringVar(value=initial_path)
        ttk.Entry(frame, textvariable=path_var).pack(fill='x', pady=(4, 10))
        ttk.Label(frame, text='File contents').pack(anchor='w')
        editor_wrap = ttk.Frame(frame)
        editor_wrap.pack(fill='both', expand=True, pady=(4, 12))
        editor = tk.Text(editor_wrap, wrap='none', font=('Consolas', 10), undo=True, padx=9, pady=8)
        yscroll = ttk.Scrollbar(editor_wrap, orient='vertical', command=editor.yview)
        xscroll = ttk.Scrollbar(editor_wrap, orient='horizontal', command=editor.xview)
        editor.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        editor.grid(row=0, column=0, sticky='nsew')
        yscroll.grid(row=0, column=1, sticky='ns')
        xscroll.grid(row=1, column=0, sticky='ew')
        editor_wrap.rowconfigure(0, weight=1)
        editor_wrap.columnconfigure(0, weight=1)
        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Button(row, text='Cancel', command=dialog.destroy).pack(side='right')

        def submit():
            try:
                file_path = clean_repo_path(path_var.get())
            except RuntimeError as exc:
                messagebox.showwarning('Invalid file path', str(exc), parent=dialog)
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

        ttk.Button(row, text='Create / save file', command=submit, style='Accent.TButton').pack(side='right', padx=(0, 8))

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
        confirm = tk.Toplevel(self.win)
        confirm.title('Confirm permanent deletion')
        confirm.geometry('480x270')
        confirm.minsize(390, 250)
        confirm.transient(self.win)
        confirm.grab_set()
        area = ttk.Frame(confirm, padding=20)
        area.pack(fill='both', expand=True)
        ttk.Label(area, text='Permanently delete repository?', font=('Segoe UI', 15, 'bold'), foreground='#b42318').pack(anchor='w')
        ttk.Label(
            area,
            text=f'This permanently deletes {destination}, including files, issues and history. This cannot be undone.',
            wraplength=420
        ).pack(anchor='w', pady=(10, 14))
        ttk.Label(area, text=f'Type {destination} to confirm:').pack(anchor='w')
        typed = tk.StringVar()
        entry = ttk.Entry(area, textvariable=typed)
        entry.pack(fill='x', pady=(5, 12))
        entry.focus_set()
        row = ttk.Frame(area)
        row.pack(fill='x')
        ttk.Button(row, text='Cancel', command=confirm.destroy).pack(side='right')

        def proceed():
            if typed.get().strip() != destination:
                messagebox.showwarning('Name does not match', 'Type the full owner/repository name exactly.', parent=confirm)
                return
            confirm.destroy()
            self.status.config(text='Deleting repository…')

            def work():
                try:
                    GitHub(self.token).delete_repo(owner, repo)
                    self.q.put(('deleted', destination))
                except Exception as exc:
                    self.q.put(('error', str(exc)))
            self.run_bg(work)

        ttk.Button(row, text='Delete permanently', style='Danger.TButton', command=proceed).pack(side='right', padx=(0, 8))

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
                    self.oauth_button.config(state='normal')
                    if self.device_dialog and self.device_dialog.winfo_exists():
                        self.device_dialog.destroy()
                    self.token = item[1]
                    self.username = item[2].get('login')
                    self.user_label.config(text=f'●  Connected as @{self.username}', foreground=self.app.palette['success'])
                    self.status.config(text='Connected. Repositories loaded automatically.')
                    self.logline(f'Connected: @{self.username}')
                    self._show_repos(item[3])
                elif kind == 'repos':
                    self._show_repos(item[1])
                elif kind == 'deleted':
                    self.logline('Deleted repository: ' + item[1])
                    self.status.config(text='Repository deleted successfully.')
                    self.repo.set('')
                    self.repo_combo.set('')
                    self.load_repos()
                    messagebox.showinfo('Repository deleted', f'{item[1]} was permanently deleted.', parent=self.win)
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
                    _, index, total, name = item
                    self.progress['maximum'] = total
                    self.progress['value'] = index
                    self.status.config(text=f'Uploading {index}/{total}: {name}')
                elif kind == 'done':
                    count, url = item[1]
                    self.push_btn.config(state='normal')
                    self.status.config(text=f'Upload complete — {count} files.')
                    self.logline(f'Success: {count} files committed. {url}')
                    messagebox.showinfo('Upload complete', f'{count} files uploaded successfully.\n\n{url}', parent=self.win)
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
            text='●  Upload projects  ·  ●  Create files & folders  ·  ●  Delete repository content\n●  Connect with token or GitHub sign-in  ·  ●  Switch between light and dark themes',
            style='Body.TLabel', wraplength=520, justify='left'
        ).pack(anchor='w')
        ttk.Label(
            frame,
            text='Open multiple independent workspaces. Each window can connect to a different GitHub account.',
            style='Hint.TLabel', wraplength=530
        ).pack(anchor='w', pady=(12, 0))
        self.root.protocol('WM_DELETE_WINDOW', self.root.destroy)

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
