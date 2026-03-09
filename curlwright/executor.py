"""Public executor composition built on top of application and infrastructure layers."""

from curlwright.application import RequestExecutor as ApplicationRequestExecutor
from curlwright.bootstrap import create_request_executor
from curlwright.domain import ResponsePayload


class RequestExecutor(ApplicationRequestExecutor):
    def __init__(
        self,
        headless: bool = False,
        timeout: int = 30,
        user_agent: str | None = None,
        no_gui: bool = False,
        cookie_file: str | None = None,
        persist_cookies: bool = True,
        bypass_state_file: str | None = None,
        artifact_dir: str | None = None,
        bypass_attempts: int = 3,
        profile_dir: str | None = None,
    ):
        wired_executor = create_request_executor(
            headless=headless,
            timeout=timeout,
            user_agent=user_agent,
            no_gui=no_gui,
            cookie_file=cookie_file,
            persist_cookies=persist_cookies,
            bypass_state_file=bypass_state_file,
            artifact_dir=artifact_dir,
            bypass_attempts=bypass_attempts,
            profile_dir=profile_dir,
        )
        super().__init__(
            parser=wired_executor.parser,
            browser_manager_factory=wired_executor.browser_manager_factory,
            http_runtime=wired_executor.http_runtime,
            page_probe=wired_executor.page_probe,
            challenge_actuator=wired_executor.challenge_actuator,
            artifact_store=wired_executor.artifact_store,
            telemetry=wired_executor.telemetry,
            bypass_policy=wired_executor.bypass_policy,
            session_store=wired_executor.session_store,
            cookie_store=wired_executor.cookie_manager,
            persist_cookies=persist_cookies,
            headless=headless,
            timeout=timeout,
            user_agent=user_agent,
            no_gui=no_gui,
            bypass_attempts=bypass_attempts,
            profile_dir=profile_dir,
        )


__all__ = ["RequestExecutor", "ResponsePayload"]
