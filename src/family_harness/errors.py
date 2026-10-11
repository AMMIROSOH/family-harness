"""Errors safe to show in the setup page, with concrete recovery steps."""


class SetupError(Exception):
    def __init__(self, code: str, message: str, recovery: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery = recovery

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "recovery": self.recovery}


def audio_error(exc: Exception) -> SetupError:
    detail = str(exc).lower()
    if "permission" in detail or "access denied" in detail:
        return SetupError(
            "permission_denied",
            "Windows denied microphone access.",
            "Open Windows Settings > Privacy & security > Microphone. Allow microphone "
            "access and desktop apps, then try again.",
        )
    return SetupError(
        "audio_unavailable",
        "The selected audio device could not be used.",
        "Reconnect the device, close other apps using it, check Windows microphone permissions "
        "and Sound settings, then refresh and select it again. Try a wired device if Bluetooth "
        "cannot provide input and output together.",
    )
