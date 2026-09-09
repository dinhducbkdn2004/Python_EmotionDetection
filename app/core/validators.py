
import re
from typing import Any
from email_validator import validate_email, EmailNotValidError


def is_valid_email(email: str) -> bool:
    """Check if email is valid."""
    try:
        validate_email(email)
        return True
    except EmailNotValidError:
        return False


def is_valid_image_filename(filename: str) -> bool:
    """Check if filename is a valid image (jpg, jpeg, png, gif)."""
    return bool(re.match(r"^.+\.(jpg|jpeg|png|gif)$", filename, re.IGNORECASE))


def is_positive_number(value: Any) -> bool:
    """Check if value is a positive number."""
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def is_non_empty_string(value: Any) -> bool:
    """Check if value is a non-empty string."""
    return isinstance(value, str) and value.strip() != ""
