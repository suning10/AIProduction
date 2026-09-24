## Code Breakdown

### Building the Command (`argv`)

```python
argv = [sys.executable, str(script_path), *(script_args or [])]
```

| Part | What it does |
|------|-------------|
| `sys.executable` | Full path to the **current Python interpreter** (e.g. `/usr/bin/python3`) |
| `str(script_path)` | The script to run, converted to a plain string |
| `*(script_args or [])` | **Unpacks** the args list, or an empty list if `script_args` is `None` |

So for `script_args = ["--input", "foo"]`, `argv` becomes:
```python
["/usr/bin/python3", "/path/to/script.py", "--input", "foo"]
```

---

### Launching the Process

```python
process = await asyncio.create_subprocess_exec(*argv, ...)
```
- `create_subprocess_exec` spawns the process **without a shell** (safer than `shell=True`)
- `*argv` unpacks the list as separate arguments
- `PIPE` captures stdout/stderr instead of printing them

---

### Waiting with a Timeout

```python
stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=...)
```
- `process.communicate()` waits for the process to **finish** and collects all output
- `wait_for` cancels it if it exceeds the timeout, raising `asyncio.TimeoutError`

---

### Timeout Handler

```python
except asyncio.TimeoutError:
    process.kill()      # sends SIGKILL immediately
    await process.wait() # reaps the zombie process
    return f"script '{script_name}' timed out..."
```
> **Important:** `kill()` without `await process.wait()` can leave a zombie process

---

### Exit Code Check

```python
if process.returncode != 0:
    error_output = stderr.decode(errors="replace").strip() or "(no error output)"
```
- `returncode != 0` means the script **signalled failure**
- `errors="replace"` handles garbled/binary output gracefully instead of crashing
- `or "(no error output)"` handles the case where stderr was empty

---

### Flow Summary

```
Build argv
    ↓
Spawn subprocess (non-blocking)
    ↓
Wait for output (with timeout)
    ↓ timeout?        → kill process → return timeout message
    ↓ bad exit code?  → decode stderr → return error message
    ↓ success         → decode stdout → use output
```