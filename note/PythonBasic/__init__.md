# Summary

## package vs directory

- package with __init__.py
- for cleaner import 

Import = Execute + cache 

- this will execute when import 
  - note this only import once 
- main.py can directly use it without init
```python
# logging.py
# Initialize logging
setup_logging()

# Create logger instance
logger = structlog.get_logger()
log_level_name = "DEBUG" if settings.DEBUG else "INFO"
logger.info(
    "logging_initialized",
    environment=settings.ENVIRONMENT.value,
    log_level=log_level_name,
    log_format=settings.LOG_FORMAT,
    debug=settings.DEBUG,
)

# in main.py
from app.core.logging import logger
```

**with __init__**
```python
# add __init__.py in core.logging

# in main.py
from app.core import logger
```

more example
```markdown
app/
├── __init__.py
├── main.py
└── core/
    ├── __init__.py  ← re-exports logger
    ├── logging.py   ← defines logger
    └── config.py
```

```python
# core/__init__.py
from app.core.logging import logger, setup_logging  # re-export

# main.py
from app.core import logger  # cleaner import
```