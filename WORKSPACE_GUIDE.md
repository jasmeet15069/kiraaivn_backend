# Jarvis Workspace

This is your persistent, shared work area on the VPS — separate from the
throwaway sandbox `run_code` uses for calculations. Anything you create here
sticks around, is visible to the user in the VPS Monitor dashboard's file
browser, and can be read back by you (or a differently-selected model) later.

## The one rule: timestamp every new piece of work

Before creating any new file, script, or small project, call the
`create_workspace_folder` tool with a short label describing what it's for:

```
create_workspace_folder({"label": "sales-report"})
→ Created workspace folder: /opt/kira-chat-backend/workspace/20260908_143012_sales-report
```

Then write every file for that piece of work inside the returned path, using
the `mcp_workspace-fs_*` tools (write_file, create_directory, edit_file,
read_text_file, list_directory, directory_tree, search_files, move_file,
get_file_info — same shape as the sandbox-fs tools you already know).

This keeps the workspace organized by *when* something was made and *what it
was for*, so the user can find things later just by glancing at folder names
— never dump files at the workspace root or reuse an old folder for a new,
unrelated task.

## Why this matters

This guide is injected into every conversation's system prompt, regardless
of which model is answering (cloud, local, or Ollama) — so whichever model
is currently selected already knows this convention without needing to read
this file. It's kept here too so you (or the user, reading it directly) have
the full explanation on hand.
