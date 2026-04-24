import importlib.metadata
import pytest
from assertpy import assert_that

from ai_contained.core.mcp import load_providers
from conftest import make_ep


def patch_entry_points(monkeypatch, *entry_points):
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: list(entry_points),
    )


def describe_load_providers():

    def describe_with_no_env_vars():
        def it_loads_all_discovered_providers(mcp, monkeypatch):
            fs = make_ep("filesystem")
            shell = make_ep("shell")
            patch_entry_points(monkeypatch, fs, shell)

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)
            assert_that(shell.load.return_value.calls).is_length(1)

        def it_returns_the_mcp_instance(mcp, monkeypatch):
            patch_entry_points(monkeypatch)

            result = load_providers(mcp)

            assert_that(result).is_same_as(mcp)

    def describe_ALLOWED_PROVIDERS():
        def it_loads_only_the_allowed_provider(mcp, monkeypatch):
            fs = make_ep("filesystem")
            shell = make_ep("shell")
            patch_entry_points(monkeypatch, fs, shell)
            monkeypatch.setenv("ALLOWED_PROVIDERS", "filesystem")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)
            assert_that(shell.load.return_value.calls).is_empty()

        def it_loads_multiple_allowed_providers(mcp, monkeypatch):
            fs = make_ep("filesystem")
            shell = make_ep("shell")
            git = make_ep("git")
            patch_entry_points(monkeypatch, fs, shell, git)
            monkeypatch.setenv("ALLOWED_PROVIDERS", "filesystem,shell")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)
            assert_that(shell.load.return_value.calls).is_length(1)
            assert_that(git.load.return_value.calls).is_empty()

        def it_loads_nothing_when_no_providers_match(mcp, monkeypatch):
            fs = make_ep("filesystem")
            patch_entry_points(monkeypatch, fs)
            monkeypatch.setenv("ALLOWED_PROVIDERS", "shell")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_empty()

        def it_is_case_sensitive(mcp, monkeypatch):
            fs = make_ep("filesystem")
            patch_entry_points(monkeypatch, fs)
            monkeypatch.setenv("ALLOWED_PROVIDERS", "Filesystem")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_empty()

        def it_does_not_load_when_name_has_surrounding_whitespace(mcp, monkeypatch):
            fs = make_ep("filesystem")
            patch_entry_points(monkeypatch, fs)
            monkeypatch.setenv("ALLOWED_PROVIDERS", " filesystem ")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_empty()

        def it_treats_comma_only_value_as_unset(mcp, monkeypatch):
            fs = make_ep("filesystem")
            patch_entry_points(monkeypatch, fs)
            monkeypatch.setenv("ALLOWED_PROVIDERS", ",")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)

    def describe_DENIED_PROVIDERS():
        def it_skips_the_denied_provider(mcp, monkeypatch):
            fs = make_ep("filesystem")
            shell = make_ep("shell")
            patch_entry_points(monkeypatch, fs, shell)
            monkeypatch.setenv("DENIED_PROVIDERS", "shell")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)
            assert_that(shell.load.return_value.calls).is_empty()

        def it_skips_multiple_denied_providers(mcp, monkeypatch):
            fs = make_ep("filesystem")
            shell = make_ep("shell")
            git = make_ep("git")
            patch_entry_points(monkeypatch, fs, shell, git)
            monkeypatch.setenv("DENIED_PROVIDERS", "shell,git")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)
            assert_that(shell.load.return_value.calls).is_empty()
            assert_that(git.load.return_value.calls).is_empty()

        def it_loads_all_when_no_providers_match_deny_list(mcp, monkeypatch):
            fs = make_ep("filesystem")
            patch_entry_points(monkeypatch, fs)
            monkeypatch.setenv("DENIED_PROVIDERS", "shell")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)

    def describe_ALLOWED_and_DENIED_together():
        def it_applies_deny_after_allow(mcp, monkeypatch):
            fs = make_ep("filesystem")
            shell = make_ep("shell")
            patch_entry_points(monkeypatch, fs, shell)
            monkeypatch.setenv("ALLOWED_PROVIDERS", "filesystem,shell")
            monkeypatch.setenv("DENIED_PROVIDERS", "shell")

            load_providers(mcp)

            assert_that(fs.load.return_value.calls).is_length(1)
            assert_that(shell.load.return_value.calls).is_empty()


    def describe_error_handling():
        def it_raises_and_halts_when_register_fails(mcp, monkeypatch):
            def bad_register(mcp):
                raise RuntimeError("register failed")

            bad = make_ep("bad")
            bad.load.return_value = bad_register
            good = make_ep("good")
            patch_entry_points(monkeypatch, bad, good)

            with pytest.raises(RuntimeError, match="register failed"):
                load_providers(mcp)

            assert_that(good.load.return_value.calls).is_empty()
