from assertpy import assert_that  # type: ignore[import-untyped]

from ai_contained.base.finalize import _local_overrides


def describe_local_overrides() -> None:
    def it_pins_each_provider_to_its_own_local_path() -> None:
        result = _local_overrides(
            ["/opt/ai-contained-provider-trust-server-daemon/", "/opt/ai-contained-provider-aws-secrets/"]
        )
        assert_that(result).contains(
            "ai-contained-provider-trust-server-daemon @ file:///opt/ai-contained-provider-trust-server-daemon"
        )
        assert_that(result).contains(
            "ai-contained-provider-aws-secrets @ file:///opt/ai-contained-provider-aws-secrets"
        )

    def it_returns_empty_for_no_providers() -> None:
        assert_that(_local_overrides([])).is_equal_to("\n")
