# Path

## join path

```python
# achieved by overload /
# skill_dir must be a path object
scripts_dir = skill_dir / "scripts"
# equal to 
import os
scripts_dir = os.path.join(skill_dir, "scripts")
```

## convert to absolute path
```python
# find all file with .py 
# glob 
return {path.name: path.resolve() for path in sorted(scripts_dir.glob("*.py")) if path.is_file()}
```