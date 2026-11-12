class TokenExpiredError(Exception):
    """Stand-in for authlib's TokenExpiredError."""


class InvalidTokenError(Exception):
    """Stand-in for authlib's InvalidTokenError."""
