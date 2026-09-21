class ApiError(Exception):
    def __init__(self, message: str, code: str = "api_error", status: int = 400, details=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.details = details or {}


class AuthenticationError(ApiError):
    def __init__(self, message: str = "Authentication required", details=None):
        super().__init__(message, code="authentication_required", status=401, details=details)


class AuthorizationError(ApiError):
    def __init__(self, message: str = "Insufficient permissions", details=None):
        super().__init__(message, code="authorization_failed", status=403, details=details)


class NotFoundError(ApiError):
    def __init__(self, message: str = "Resource not found", details=None):
        super().__init__(message, code="not_found", status=404, details=details)


class ConflictError(ApiError):
    def __init__(self, message: str, code: str = "conflict", details=None):
        super().__init__(message, code=code, status=409, details=details)


class ValidationError(ApiError):
    def __init__(self, message: str, details=None, code: str = "validation_error"):
        super().__init__(message, code=code, status=422, details=details)


def register_error_handlers(app):
    from .api.responses import error_response

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.message, exc.code, exc.status, exc.details)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("Resource not found", "not_found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response("Method not allowed", "method_not_allowed", 405)

    @app.errorhandler(422)
    def handle_unprocessable(exc):
        return error_response(
            str(exc.description or "Unprocessable entity"), "validation_error", 422
        )

    @app.errorhandler(500)
    def handle_internal(exc):
        app.logger.exception("Unhandled error")
        return error_response("Internal server error", "internal_error", 500)
