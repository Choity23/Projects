import os
import base64
import threading
import queue
import json
import urllib.request
import urllib.error
import urllib.parse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from pathlib import Path

APP_NAME = 'RepoPilot'
API = 'https://api.github.com'


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
        self.win.geometry('900x760')
        self.win.minsize(390, 360)
        self.win.configure(bg='#f3f6fc')
        self.token = None
        self.username = None
        self.folder = tk.StringVar()
        self.repo = tk.StringVar()
        self.branch = tk.StringVar(value='main')
        self.repo_path = tk.StringVar()
        self.q = queue.Queue()
        self._build()
        self.win.after(120, self._poll)

    def _build(self):
        shell = ttk.Frame(self.win, padding=10)
        shell.pack(fill='both', expand=True)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)

        canvas = tk.Canvas(shell, highlightthickness=0, bg='#f3f6fc')
        scrollbar = ttk.Scrollbar(shell, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar.grid(row=0, column=1, sticky='ns')
        content = ttk.Frame(canvas, padding=(7, 5, 7, 14))
        content_id = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda _event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(content_id, width=event.width))

        def wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')
        canvas.bind_all('<MouseWheel>', wheel, add='+')

        header = ttk.Frame(content)
        header.pack(fill='x', pady=(0, 10))
        ttk.Label(header, text='RepoPilot', font=('Segoe UI', 23, 'bold'), foreground='#142d50').pack(anchor='w')
        ttk.Label(
            header,
            text=f'GitHub workspace #{self.number}  ·  Upload, create and manage repository content',
            wraplength=720, foreground='#62728a'
        ).pack(anchor='w', pady=(2, 0))

        auth = ttk.LabelFrame(content, text='  1  ·  Connect GitHub account  ', padding=11)
        auth.pack(fill='x', pady=5)
        tokenrow = ttk.Frame(auth)
        tokenrow.pack(fill='x')
        self.token_entry = ttk.Entry(tokenrow, show='•')
        self.token_entry.pack(side='left', fill='x', expand=True, padx=(0, 8))
        ttk.Button(tokenrow, text='Verify & load repositories', command=self.login, style='Accent.TButton').pack(side='left')
        self.user_label = ttk.Label(auth, text='Not connected', foreground='#64748b')
        self.user_label.pack(anchor='w', pady=(8, 0))
        ttk.Label(
            auth,
            text='Use a GitHub Personal Access Token with repository Contents read/write access. Repository deletion also needs Administration permission.',
            wraplength=760, foreground='#68788f'
        ).pack(anchor='w', pady=(4, 0))

        dest = ttk.LabelFrame(content, text='  2  ·  Choose repository & destination  ', padding=11)
        dest.pack(fill='x', pady=5)
        dest.columnconfigure(1, weight=1)
        ttk.Label(dest, text='Repository').grid(row=0, column=0, sticky='w', padx=(0, 8), pady=4)
        ttk.Entry(dest, textvariable=self.repo).grid(row=0, column=1, sticky='ew', pady=4)
        ttk.Label(dest, text='Branch').grid(row=1, column=0, sticky='w', padx=(0, 8), pady=4)
        ttk.Entry(dest, textvariable=self.branch).grid(row=1, column=1, sticky='ew', pady=4)
        ttk.Label(dest, text='Upload destination').grid(row=2, column=0, sticky='w', padx=(0, 8), pady=4)
        ttk.Entry(dest, textvariable=self.repo_path).grid(row=2, column=1, sticky='ew', pady=4)
        ttk.Label(
            dest, text='Leave blank for repository root, or enter a folder path such as: my game/assets',
            wraplength=680, foreground='#68788f'
        ).grid(row=3, column=1, sticky='w', pady=(0, 5))

        repo_row = ttk.Frame(dest)
        repo_row.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(5, 4))
        ttk.Label(repo_row, text='Your repositories', foreground='#51627a').pack(side='left')
        ttk.Button(repo_row, text='↻ Refresh', command=self.load_repos).pack(side='right')
        self.repo_combo = ttk.Combobox(dest, state='readonly')
        self.repo_combo.grid(row=5, column=0, columnspan=2, sticky='ew', pady=3)
        self.repo_combo.bind('<<ComboboxSelected>>', self.pick_repo)

        tools = ttk.Frame(dest)
        tools.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(7, 0))
        ttk.Label(tools, text='Repository tools', foreground='#51627a').pack(side='left')
        ttk.Button(tools, text='+ Create folder', command=self.create_folder).pack(side='left', padx=(10, 5))
        ttk.Button(tools, text='+ Create file', command=self.create_file_dialog).pack(side='left', padx=5)
        ttk.Button(tools, text='Delete repository…', style='Danger.TButton', command=self.delete_repo).pack(side='right')

        src = ttk.LabelFrame(content, text='  3  ·  Select local project  ', padding=11)
        src.pack(fill='x', pady=5)
        folderrow = ttk.Frame(src)
        folderrow.pack(fill='x')
        ttk.Entry(folderrow, textvariable=self.folder).pack(side='left', fill='x', expand=True, padx=(0, 8))
        ttk.Button(folderrow, text='Browse…', command=self.browse).pack(side='left')
        ttk.Label(
            src, text='The selected folder contents will be uploaded into the destination path above. Existing files with matching paths are updated; other repository files are preserved.',
            wraplength=760, foreground='#68788f'
        ).pack(anchor='w', pady=(7, 0))

        logbox = ttk.LabelFrame(content, text='  Activity  ', padding=8)
        logbox.pack(fill='both', expand=True, pady=(8, 4))
        self.log = tk.Text(
            logbox, height=7, wrap='word', state='disabled', bg='#ffffff', fg='#20334c',
            relief='flat', font=('Consolas', 9), padx=10, pady=8
        )
        self.log.pack(fill='both', expand=True)

        footer = ttk.Frame(shell, padding=(4, 9, 4, 2))
        footer.grid(row=1, column=0, columnspan=2, sticky='ew')
        footer.columnconfigure(0, weight=1)
        buttons = ttk.Frame(footer)
        buttons.pack(fill='x')
        self.push_btn = ttk.Button(buttons, text='↑  PUSH PROJECT TO GITHUB', command=self.push, style='Accent.TButton')
        self.push_btn.pack(side='left', fill='x', expand=True, ipady=6)
        ttk.Button(buttons, text='Open repository ↗', command=self.open_repo).pack(side='left', padx=(8, 0))
        self.progress = ttk.Progressbar(footer, mode='determinate')
        self.progress.pack(fill='x', pady=(7, 3))
        self.status = ttk.Label(footer, text='Ready. Connect an account to begin.', foreground='#52647c', wraplength=760)
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
                if kind == 'login':
                    self.token = item[1]
                    self.username = item[2].get('login')
                    self.user_label.config(text=f'Connected as @{self.username}', foreground='#18794e')
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
    def __init__(self):
        self.root = tk.Tk()
        self._style()
        self.root.title('RepoPilot — GitHub Multi-Account Uploader')
        self.root.geometry('560x350')
        self.root.resizable(True, True)
        self.root.minsize(360, 260)
        frame = ttk.Frame(self.root, padding=25)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='RepoPilot', font=('Segoe UI', 27, 'bold'), foreground='#142d50').pack(anchor='w')
        ttk.Label(
            frame,
            text='One portable desktop app. Multiple independent GitHub accounts and repository workspaces.',
            wraplength=480, foreground='#64748b'
        ).pack(anchor='w', pady=(5, 20))
        ttk.Button(frame, text='+  Open new account / upload window', command=self.new_window, style='Accent.TButton').pack(fill='x', ipady=11)
        ttk.Label(
            frame,
            text='Open as many independent workspaces as your PC can handle. Each window can connect to a different GitHub account and repository.',
            wraplength=480
        ).pack(anchor='w', pady=16)
        ttk.Label(frame, text='Security: access tokens stay in memory only and are not written to disk.', foreground='#64748b', wraplength=480).pack(anchor='w')
        self.count = 0
        self.root.protocol('WM_DELETE_WINDOW', self.root.destroy)

    def _style(self):
        style = ttk.Style(self.root)
        if 'clam' in style.theme_names():
            style.theme_use('clam')
        self.root.configure(bg='#f3f6fc')
        style.configure('.', font=('Segoe UI', 10), background='#f3f6fc', foreground='#18263b')
        style.configure('TFrame', background='#f3f6fc')
        style.configure('TLabelframe', background='#f3f6fc', bordercolor='#d5dfec', relief='solid')
        style.configure('TLabelframe.Label', font=('Segoe UI', 10, 'bold'), foreground='#17345d', background='#f3f6fc')
        style.configure('TLabel', background='#f3f6fc', foreground='#27384e')
        style.configure('TButton', padding=(12, 8), background='#e4ebf6', foreground='#183a68', borderwidth=0)
        style.map('TButton', background=[('active', '#d3e3f9'), ('pressed', '#bdd5f4')])
        style.configure('Accent.TButton', padding=(13, 9), background='#1f5fbf', foreground='#ffffff', borderwidth=0, font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('active', '#174f9f'), ('pressed', '#123f80')], foreground=[('disabled', '#d9e4f3')])
        style.configure('Danger.TButton', background='#fff0f0', foreground='#ad2525')
        style.map('Danger.TButton', background=[('active', '#ffe0e0')])
        style.configure('TEntry', padding=7, fieldbackground='#ffffff')
        style.configure('TCombobox', padding=7, fieldbackground='#ffffff')
        style.configure('TProgressbar', background='#3679e8', troughcolor='#e0e9f5')

    def new_window(self):
        self.count += 1
        AccountWindow(self, self.count)

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()
