from __future__ import annotations

import logging


class RedactingLogger:
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def info_delivery_profile_used(self, profile_id: str) -> None:
        self.logger.info("delivery_profile_used delivery_profile_id=%s", profile_id)
