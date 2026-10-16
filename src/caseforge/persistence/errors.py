"""Record storage errors."""


class RecordStoreError(Exception):
    """Raised for storage failures and incompatible storage state."""


class RecordConflictError(RecordStoreError):
    """Raised when a record id already exists with different content."""


class LedgerTransitionError(RecordStoreError):
    """Raised when an action-ledger status change is not allowed."""
