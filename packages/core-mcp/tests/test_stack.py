import asyncio
import json
from pathlib import Path

import pytest
from assertpy import assert_that
from fastmcp import Context
from fastmcp.exceptions import ToolError

from ai_contained.core.mcp.context import ProviderContext
from ai_contained.core.mcp.stack import ExecResponse, Stack


async def run(stack: Stack, *argv: str) -> tuple[int, str, str]:
    """Spawn a command the way providers do (PiperProcess/CredentialsManager): argv + explicit env."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        env=dict(stack.env),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    assert proc.returncode is not None
    return proc.returncode, stdout.decode(), stderr.decode()


def describe_Stack() -> None:
    def describe_install() -> None:
        # Mirrors the aws-cli conftest: install providers in dependency order,
        # each seeing the merged env, later ones ensure()-ing earlier ones.

        async def it_runs_the_provider_and_returns_its_state() -> None:
            expected = object()

            async def provide(ctx: ProviderContext) -> object:
                return expected

            async with Stack() as s:
                assert_that(await s.install(provide)).is_same_as(expected)

        async def it_merges_env_before_running_the_provider() -> None:
            seen: dict[str, str] = {}

            async def provide(ctx: ProviderContext) -> None:
                seen.update(ctx.environ)

            async with Stack(env={"COLOR": "off"}) as s:
                await s.install(provide, env={"AWS_ACCOUNTS_CONFIG_PATH": "/tmp/accounts.json5"})

            assert_that(seen["COLOR"]).is_equal_to("off")
            assert_that(seen["AWS_ACCOUNTS_CONFIG_PATH"]).is_equal_to("/tmp/accounts.json5")

        async def it_lets_a_later_install_ensure_an_earlier_one() -> None:
            # aws_cli ensures trust_client — the composition every fixture relies on.
            registry = object()

            async def trust_client(ctx: ProviderContext) -> object:
                return registry

            received: list[object | None] = []

            async def aws_cli(ctx: ProviderContext) -> None:
                received.append(await ctx.ensure(trust_client))

            async with Stack() as s:
                await s.install(trust_client)
                await s.install(aws_cli)

            assert_that(received).contains(registry)

        async def it_propagates_a_providers_failure() -> None:
            # Same raise-and-halt contract as load_providers: a broken fixture
            # composition must fail loudly at install, not at first tool call.
            async def bad(ctx: ProviderContext) -> None:
                raise RuntimeError("provide failed")

            async with Stack() as s:
                with pytest.raises(RuntimeError, match="provide failed"):
                    await s.install(bad)

    def describe_add() -> None:
        async def it_substitutes_a_state_without_running_the_provider() -> None:
            # The isolated-test seam: aws_cli against a hand-built TrustRegistry,
            # no trust stack installed.
            fake_registry = object()

            async def trust_client(ctx: ProviderContext) -> object:
                raise AssertionError("substituted provider must not run")

            received: list[object | None] = []

            async def aws_cli(ctx: ProviderContext) -> None:
                received.append(await ctx.ensure(trust_client))

            async with Stack() as s:
                s.add(trust_client, fake_registry)
                await s.install(aws_cli)

            assert_that(received).contains(fake_registry)

    def describe_write() -> None:
        async def it_writes_a_file_and_returns_its_path() -> None:
            # aws-secrets reads AWS_ACCOUNTS_CONFIG_PATH from disk in provide().
            expected = '{ login: { type: "sso" }, accounts: {} }'
            async with Stack() as s:
                path = s.write("accounts.json5", expected)
                assert_that(Path(path).read_text()).is_equal_to(expected)

        async def it_creates_parent_directories_for_nested_paths() -> None:
            # provider-filesystem tests build trees like glob_test/sub/deep/f.txt.
            async with Stack() as s:
                path = s.write("glob_test/sub/deep/f.txt", "content")
                assert_that(Path(path).read_text()).is_equal_to("content")

        async def it_removes_the_tmpdir_on_teardown() -> None:
            async with Stack() as s:
                path = s.write("accounts.json5", "{}")
            assert_that(Path(path).exists()).is_false()

    def describe_exec() -> None:
        # Replaces tests/bin/aws + the MOCK_AWS_* env vars in aws-cli, and
        # mock_aws_sts.sh / mock_aws_export.sh / mock_aws_sso_login.sh in aws-secrets.

        async def it_returns_the_default_response() -> None:
            async with Stack() as s:
                s.exec("aws").returns(ExecResponse(stdout='{"Buckets": []}', stderr="warn", exit_code=0))
                code, out, err = await run(s, "aws", "s3api", "list-buckets")
            assert_that(code).is_equal_to(0)
            assert_that(out).is_equal_to('{"Buckets": []}')
            assert_that(err).is_equal_to("warn")

        async def it_reflects_a_nonzero_exit_code() -> None:
            # aws-cli surfaces aws stderr/exit 255 verbatim.
            async with Stack() as s:
                s.exec("aws").returns(ExecResponse(stderr="command not found", exit_code=255))
                code, out, err = await run(s, "aws", "s3api", "list-buckets")
            assert_that(code).is_equal_to(255)
            assert_that(err).is_equal_to("command not found")

        async def it_matches_the_longest_argv_prefix() -> None:
            # CredentialsManager calls sts get-caller-identity and
            # configure export-credentials on the same binary.
            async with Stack() as s:
                shim = s.exec("aws")
                shim.returns(ExecResponse(exit_code=1))
                shim.on("sts", "get-caller-identity").returns(ExecResponse(stdout='{"Account": "123456789012"}'))
                sts_code, sts_out, _ = await run(s, "aws", "sts", "get-caller-identity")
                other_code, _, _ = await run(s, "aws", "s3api", "list-buckets")
            assert_that(sts_code).is_equal_to(0)
            assert_that(json.loads(sts_out)["Account"]).is_equal_to("123456789012")
            assert_that(other_code).is_equal_to(1)

        async def it_reconfigures_between_spawns() -> None:
            # Replaces monkeypatch.setenv("MOCK_JQ_EXIT_CODE", ...) mid-test:
            # rules are read at each invocation.
            async with Stack() as s:
                s.exec("jq").returns(ExecResponse(stdout="[]"))
                first_code, first_out, _ = await run(s, "jq", ".Buckets")
                s.exec("jq").returns(ExecResponse(stderr="parse error", exit_code=1))
                second_code, _, second_err = await run(s, "jq", ".Buckets")
            assert_that((first_code, first_out)).is_equal_to((0, "[]"))
            assert_that((second_code, second_err)).is_equal_to((1, "parse error"))

        async def it_serves_a_sequence_with_the_last_response_repeating() -> None:
            # mock_aws_sso_login.sh: the login loop polls a nondeterministic
            # number of times — the URL once, then success for every call after.
            async with Stack() as s:
                s.exec("aws").on("sso", "login").returns(
                    ExecResponse(stdout="https://device.sso.fake.example.com/activate\n", exit_code=1),
                    ExecResponse(stdout="ok\n", exit_code=0),
                )
                first = await run(s, "aws", "sso", "login")
                second = await run(s, "aws", "sso", "login")
                third = await run(s, "aws", "sso", "login")
            assert_that(first[0]).is_equal_to(1)
            assert_that(first[1]).contains("device.sso.fake.example.com")
            assert_that(second[0]).is_equal_to(0)
            assert_that(third[0]).is_equal_to(0)

        async def it_pipes_one_shim_into_another() -> None:
            # The PiperProcess topology: aws stdout -> jq stdin. The jq shim
            # must drain stdin, or a large aws payload blocks the pipe and
            # hangs the pipeline (why tests/bin/jq starts with `cat >/dev/null`).
            payload = "x" * 100_000  # larger than a pipe buffer
            async with Stack() as s:
                s.exec("aws").returns(ExecResponse(stdout=payload))
                s.exec("jq").returns(ExecResponse(stdout="[]"))
                aws = await asyncio.create_subprocess_exec(
                    "aws", "s3api", "list-buckets", env=dict(s.env), stdout=asyncio.subprocess.PIPE
                )
                jq = await asyncio.create_subprocess_exec(
                    "jq", ".Buckets", env=dict(s.env), stdin=aws.stdout, stdout=asyncio.subprocess.PIPE
                )
                out, _ = await jq.communicate()
                assert_that(await aws.wait()).is_equal_to(0)
                assert_that(out.decode()).is_equal_to("[]")
                assert_that(s.exec("aws").calls).is_length(1)
                assert_that(s.exec("jq").calls).is_length(1)

        async def it_does_not_resolve_unstubbed_commands() -> None:
            # stack.env's PATH contains only the shim dir: a provider spawning
            # a binary the test didn't stub must fail loudly, never fall
            # through to the real system binary (e.g. real aws in CI).
            async with Stack() as s:
                with pytest.raises(FileNotFoundError):
                    await run(s, "sh", "-c", "true")

        async def it_records_nothing_when_never_invoked() -> None:
            # Rejection tests assert the command was never spawned: filters
            # must reject before exec, not after.
            async with Stack() as s:
                s.exec("aws").returns(ExecResponse())
                assert_that(s.exec("aws").calls).is_empty()

        async def it_records_argv_per_call() -> None:
            # aws-cli tests assert the exact command construction (--output=json etc.).
            async with Stack() as s:
                s.exec("aws").returns(ExecResponse())
                await run(s, "aws", "s3api", "list-buckets", "--output=json", "--region=eu-west-1")
                calls = s.exec("aws").calls
            assert_that(calls).is_length(1)
            assert_that(calls[0].argv).is_equal_to(["s3api", "list-buckets", "--output=json", "--region=eu-west-1"])

        async def it_records_the_environment_of_each_call() -> None:
            # Replaces MOCK_JQ_ENV_DUMP: it_does_not_expose_aws_credentials_to_jq
            # asserts the spawned jq never sees AWS_* credentials.
            async with Stack() as s:
                s.exec("jq").returns(ExecResponse())
                proc = await asyncio.create_subprocess_exec(
                    "jq",
                    ".",
                    env={**stack_env_without_aws(s), "HOME": "/root"},
                )
                await proc.wait()
                jq_env = s.exec("jq").calls[0].env
            assert_that(jq_env).does_not_contain_key("AWS_SECRET_ACCESS_KEY")
            assert_that(jq_env["HOME"]).is_equal_to("/root")

    def describe_client() -> None:
        # Replaces the tool_client decorator and WrapCallToolResult(**vars(...))
        # construction across all three repos.

        async def _provider_with_tools(ctx: ProviderContext) -> None:
            @ctx.mcp.tool()
            async def greet(name: str) -> dict[str, str]:
                return {"hello": name}

            @ctx.mcp.tool()
            async def reject() -> str:
                raise ToolError("'ec2 create-instance': command is not recognized as read-only")

            @ctx.mcp.tool()
            async def confirm(ctx: Context) -> str:
                result = await ctx.elicit(message="I will run: aws s3api list-buckets", response_type=None)
                if result.action != "accept":
                    raise ToolError("Command declined: aws s3api list-buckets")
                return "ran"

        async def it_calls_a_tool_and_parses_json() -> None:
            async with Stack() as s:
                await s.install(_provider_with_tools)
                async with s.client() as c:
                    result = await c.tool("greet")(name="world")
            assert_that(result.is_error).is_false()
            assert_that(result.json()).is_equal_to({"hello": "world"})

        async def it_returns_tool_errors_without_raising() -> None:
            # Every rejection test reads result.is_error + content text.
            async with Stack() as s:
                await s.install(_provider_with_tools)
                async with s.client() as c:
                    result = await c.tool("reject")()
            assert_that(result.is_error).is_true()
            assert_that(result.content[0].text).contains("not recognized as read-only")

        async def it_accepts_a_scripted_elicitation() -> None:
            async with Stack() as s:
                await s.install(_provider_with_tools)
                s.elicit.accept(expect_message="I will run: aws s3api list-buckets")
                async with s.client() as c:
                    result = await c.tool("confirm")()
            assert_that(result.is_error).is_false()

        async def it_declines_a_scripted_elicitation() -> None:
            async with Stack() as s:
                await s.install(_provider_with_tools)
                s.elicit.decline()
                async with s.client() as c:
                    result = await c.tool("confirm")()
            assert_that(result.is_error).is_true()
            assert_that(result.content[0].text).is_equal_to("Command declined: aws s3api list-buckets")

        async def it_fails_teardown_when_scripted_elicitations_remain() -> None:
            # Replaces the hand-rolled `assert not elicitor._queue` in every fixture.
            with pytest.raises(AssertionError):
                async with Stack() as s:
                    s.elicit.accept()

        async def it_does_not_mask_a_test_body_failure_with_the_drain_check() -> None:
            # A failing test usually leaves elicitations unconsumed; the
            # developer needs the body's exception, not the drain assertion.
            with pytest.raises(ValueError, match="body failed"):
                async with Stack() as s:
                    s.elicit.accept()
                    raise ValueError("body failed")


def stack_env_without_aws(stack: Stack) -> dict[str, str]:
    """What AwsCliTool passes to jq: the stack env stripped of AWS_* credentials."""
    return {k: v for k, v in stack.env.items() if not k.startswith("AWS_")}
