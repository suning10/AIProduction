# Summary

# how to configure env 

- inline 
  - [use this](#use-inline-)
- .env
  - must use load_dotenv for python to read
- shell set env 


```markdown
Method	Example
Shell export	export APP_ENV=production
Inline command	APP_ENV=staging python app.py
.env file (needs python-dotenv)	APP_ENV=production
```

### use inline 
```python
def get_environment() -> Environment:
    """Get the current environment.

    Returns:
        Environment: The current environment (development, staging, production, or test)
    """
    match os.getenv("APP_ENV", "development").lower():
        case "production" | "prod":
            return Environment.PRODUCTION
        case "staging" | "stage":
            return Environment.STAGING
        case "test":
            return Environment.TEST
        case _:
            return Environment.DEVELOPMENT
```

