"""The household's time zone without the system's time zone files, as on Windows.

Windows has no IANA time zone database, so `zoneinfo` finds "Asia/Manila" only through the `tzdata`
package. Without it, the timeline and decisions answered 500 on Pim's laptop (Nov 25).
"""

from __future__ import annotations

import zoneinfo
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def no_system_zones() -> Iterator[None]:
    zoneinfo.reset_tzpath(to=[])
    zoneinfo.ZoneInfo.clear_cache()
    try:
        yield
    finally:
        zoneinfo.reset_tzpath()
        zoneinfo.ZoneInfo.clear_cache()


def test_manila_is_found_without_the_system_zone_files(no_system_zones: None) -> None:
    assert zoneinfo.TZPATH == ()
    manila = zoneinfo.ZoneInfo("Asia/Manila")
    assert datetime(2026, 11, 20, 20, 30, tzinfo=manila).utcoffset() == timedelta(hours=8)
