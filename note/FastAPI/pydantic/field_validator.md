# Summary

## how to add a validator in schema
- validate a field
- validate multiple field
- validate entire model

### validate a field
```python
class Message(BaseModel):
    """Message model for chat endpoint.

    Attributes:
        role: The role of the message sender (user or assistant).
        content: The content of the message.
    """

    model_config = {"extra": "ignore"}

    role: Literal["user", "assistant", "system"] = Field(..., description="The role of the message sender")
    content: str = Field(..., description="The content of the message", min_length=1, max_length=3000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate the message content.

        Args:
            v: The content to validate

        Returns:
            str: The validated content

        Raises:
            ValueError: If the content contains disallowed patterns
        """
        # Check for potentially harmful content
        if re.search(r"<script.*?>.*?</script>", v, re.IGNORECASE | re.DOTALL):
            raise ValueError("Content contains potentially harmful script tags")

        # Check for null bytes
        if "\0" in v:
            raise ValueError("Content contains null bytes")

        return v
```

### validate entire model
```python
from pydantic import BaseModel, model_validator

class UserRange(BaseModel):
    min_age: int
    max_age: int

    @model_validator(mode="after")
    def check_age_range(self):
        if self.min_age >= self.max_age:
            raise ValueError("min_age must be less than max_age")
        return self
```

### validate multiple fields
```python
from pydantic import BaseModel, field_validator

class User(BaseModel):
    first_name: str
    last_name: str

    @field_validator("first_name", "last_name")
    @classmethod
    def names_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Name cannot be empty")
        return v.title()
```