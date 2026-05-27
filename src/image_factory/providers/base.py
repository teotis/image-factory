from __future__ import annotations


class ApiDisabledError(RuntimeError):
    """Raised when a provider API call is blocked by the project safety switch."""


class ProviderUnsupportedError(RuntimeError):
    """Raised when a requested provider is not implemented for the requested operation."""
