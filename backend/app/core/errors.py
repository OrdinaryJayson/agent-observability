class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message = status, code, message
        self.details = details or {}


def not_found() -> AppError:
    return AppError(404, "RESOURCE_NOT_FOUND", "Resource not found")
