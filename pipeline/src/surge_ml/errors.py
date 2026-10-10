"""Lỗi duy nhất cho các lỗi hiển thị cho người dùng; CLI in `code: message` rồi thoát với mã 1."""


class SurgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
