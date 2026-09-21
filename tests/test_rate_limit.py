"""Tests for surviving the API's rate limiter.

Reading a long history sends one request per week, and past roughly a year
of them the API starts answering 429. It used to surface as a bare exception
that killed the whole backfill, losing every week still to come.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from custom_components.aigues_barcelona.api import RATE_LIMIT_DEFAULT_WAIT
from custom_components.aigues_barcelona.api import RATE_LIMIT_MAX_WAIT
from custom_components.aigues_barcelona.api import AiguesApiClient
from custom_components.aigues_barcelona.api import RateLimited


def response(status: int, body: str = "{}", headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = body
    resp.headers = headers or {}
    resp.json.return_value = {"message": body}
    return resp


@pytest.fixture
def client() -> AiguesApiClient:
    return AiguesApiClient("12345678Z", "hunter2", "629067")


class TestHowLongToWait:
    def test_prefers_the_retry_after_header(self):
        resp = response(429, headers={"Retry-After": "12"})
        assert AiguesApiClient._retry_after(resp, "whatever") == 12

    def test_falls_back_to_the_wording_in_the_body(self):
        """This API sends no header, only prose."""
        msg = "Rate limit is exceeded. Try again in 30 seconds."
        assert AiguesApiClient._retry_after(response(429), msg) == 30

    def test_never_believes_a_one_second_reprieve(self):
        """It always claims one second, and obeying it trips the limiter again."""
        msg = "Rate limit is exceeded. Try again in 1 seconds."
        assert (
            AiguesApiClient._retry_after(response(429), msg) == RATE_LIMIT_DEFAULT_WAIT
        )

    def test_caps_an_absurd_wait(self):
        msg = "Try again in 8000 seconds."
        assert AiguesApiClient._retry_after(response(429), msg) == RATE_LIMIT_MAX_WAIT

    def test_uses_the_default_when_told_nothing(self):
        assert (
            AiguesApiClient._retry_after(response(429), "no") == RATE_LIMIT_DEFAULT_WAIT
        )


class TestRetrying:
    def test_waits_and_tries_again(self, client):
        answers = [
            RateLimited("Rate-Limited", 1),
            RateLimited("Rate-Limited", 1),
            response(200),
        ]

        def attempt(*args, **kwargs):
            reply = answers.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply

        with (
            patch.object(client, "_request", side_effect=attempt),
            patch("custom_components.aigues_barcelona.api.time.sleep") as sleep,
        ):
            assert client._query("/anything").status_code == 200

        assert sleep.call_count == 2

    def test_gives_up_eventually(self, client):
        """A limiter that never lets go has to surface, not loop forever."""
        with (
            patch.object(client, "_request", side_effect=RateLimited("nope", 1)),
            patch("custom_components.aigues_barcelona.api.time.sleep"),
            pytest.raises(RateLimited),
        ):
            client._query("/anything")

    def test_other_errors_are_not_retried(self, client):
        with (
            patch.object(client, "_request", side_effect=Exception("Denied")) as req,
            pytest.raises(Exception, match="Denied"),
        ):
            client._query("/anything")

        assert req.call_count == 1
