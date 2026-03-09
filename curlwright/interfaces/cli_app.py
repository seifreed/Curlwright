"""CLI presenter/orchestrator for the interface layer."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from curlwright.bootstrap import create_request_executor
from curlwright.cli_parser import CLI
from curlwright.interfaces.contracts import build_failure_payload, get_exit_code, serialize_output_payload
from curlwright.interfaces.sarif import write_sarif_report
from curlwright.logger import setup_logger
from curlwright.models import ResponsePayload
from curlwright.runtime import ensure_supported_python

ensure_supported_python()

logger = setup_logger(__name__)


def _resolve_curl_command(args) -> str:
    if args.file:
        return Path(args.file).read_text().strip()
    if args.curl:
        return args.curl
    raise ValueError("No curl command provided")


def _log_execution_summary(result: ResponsePayload) -> None:
    meta = result.get("meta", {})
    if not isinstance(meta, dict):
        return
    final = meta.get("final", {})
    runtime = meta.get("runtime", {})
    state = meta.get("state", {})
    attempts = meta.get("attempts", [])
    logger.info(
        "Execution summary: attempts=%s status=%s url=%s trusted_session=%s artifact_dir=%s",
        len(attempts) if isinstance(attempts, list) else 0,
        final.get("status") if isinstance(final, dict) else None,
        final.get("url") if isinstance(final, dict) else None,
        state.get("trusted_session_before_request") if isinstance(state, dict) else None,
        runtime.get("artifact_dir") if isinstance(runtime, dict) else None,
    )


def _write_result_output(
    result: ResponsePayload,
    output_path: str | None,
    verbose: bool,
    json_output: bool,
) -> None:
    rendered_output = serialize_output_payload(result, json_output)
    if output_path:
        Path(output_path).write_text(rendered_output)
        logger.info("Response saved to %s", output_path)
        return

    if verbose and not json_output:
        print(f"Status: {result['status']}")
        print(f"Headers: {result['headers']}")
        meta = result.get("meta", {})
        if isinstance(meta, dict):
            final = meta.get("final", {})
            runtime = meta.get("runtime", {})
            state = meta.get("state", {})
            attempts = meta.get("attempts", [])
            print(f"Final URL: {final.get('url', result.get('url', ''))}")
            print(f"Attempts: {len(attempts)}")
            print(f"Trusted Session: {state.get('trusted_session_before_request')}")
            print(f"Artifacts: {runtime.get('artifact_dir')}")
        print("-" * 50)
    print(rendered_output)


async def main() -> None:
    cli = CLI()
    args = cli.parse_arguments()
    executor = None

    try:
        setup_logger(__name__, logging.DEBUG if args.verbose else logging.INFO)
        headless_mode = args.headless or args.no_gui
        executor = create_request_executor(
            headless=headless_mode,
            timeout=args.timeout,
            user_agent=args.user_agent,
            no_gui=args.no_gui,
            cookie_file=args.cookie_file,
            persist_cookies=not args.no_persist_cookies,
            bypass_state_file=args.state_file,
            artifact_dir=args.artifact_dir,
            bypass_attempts=args.bypass_attempts,
            profile_dir=args.profile_dir,
        )
        curl_command = _resolve_curl_command(args)
        result = await executor.execute(
            curl_command,
            max_retries=args.retries,
            delay=args.delay,
        )
        _log_execution_summary(result)
        write_sarif_report(args.sarif_output, result=result)
        _write_result_output(result, args.output, args.verbose, args.json_output)
    except Exception as error:
        exit_code = get_exit_code(error)
        write_sarif_report(getattr(args, "sarif_output", None), error=error)
        if args.json_output:
            print(json.dumps(build_failure_payload(error), indent=2, sort_keys=True))
        logger.error("Error: %s", error)
        sys.exit(exit_code)
    finally:
        if executor is not None:
            await executor.close()
