class WeiboDownloaderError(Exception):
    """Base exception for expected application errors."""


class AuthError(WeiboDownloaderError):
    """Raised when Weibo rejects the supplied login credentials."""


class CookieError(WeiboDownloaderError):
    """Raised when a cookie file cannot be parsed."""


class ProfileResolutionError(WeiboDownloaderError):
    """Raised when a profile URL cannot be mapped to a numeric UID."""


class WeiboAPIError(WeiboDownloaderError):
    """Raised when Weibo returns an unexpected API response."""


class StateError(WeiboDownloaderError):
    """Raised when the local download state is invalid."""


class DownloadError(WeiboDownloaderError):
    """Raised when all image candidates for one picture fail."""
