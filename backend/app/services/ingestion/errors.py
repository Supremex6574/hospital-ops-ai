class IngestError(Exception):
    """A problem with an uploaded file that the user can fix. The message is safe to show to them."""

    def __init__(self, message: str, code: str = "invalid_file", details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or []
