Command path rule:
- Filesystem tools use repository-rooted virtual paths such as /path/to/file.
- The execute tool runs in the shell-visible repository root. For shell
  commands, prefer repo-relative paths such as path/to/file, or first run pwd
  and use the absolute path visible to the shell.
- Do not pass filesystem-tool virtual paths like /path/to/file to shell
  commands unless you have verified they exist in the shell environment.
