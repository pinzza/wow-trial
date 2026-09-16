"""WCL Parser 异常定义"""


class WCLParserError(Exception):
    """基础异常"""
    pass


class WCLAPIError(WCLParserError):
    """API 层错误"""
    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class WCLAuthError(WCLAPIError):
    """认证失败"""
    pass


class WCLRateLimitError(WCLAPIError):
    """限速触发"""
    pass


class WCLParseError(WCLParserError):
    """解析层错误"""
    pass


class WCLStorageError(WCLParserError):
    """存储层错误"""
    pass
