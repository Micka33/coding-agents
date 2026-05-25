from __future__ import annotations

import unittest

from coding_agents.redaction import redact_secrets


class RedactionTests(unittest.TestCase):
    def test_redacts_url_credentials_and_common_key_values(self) -> None:
        message = (
            "postgres://dbuser:dbpass@localhost/app "
            "password=hunter2 token='tok-secret' api_key=sk-test apikey=legacy secret=hidden"
        )

        redacted = redact_secrets(message, env={})

        self.assertIn("postgres://***:***@localhost/app", redacted)
        for secret in ("dbuser", "dbpass", "hunter2", "tok-secret", "sk-test", "legacy", "hidden"):
            self.assertNotIn(secret, redacted)
        self.assertIn("password=<redacted>", redacted)
        self.assertIn("token='<redacted>'", redacted)
        self.assertIn("api_key=<redacted>", redacted)

    def test_redacts_values_from_sensitive_environment_names(self) -> None:
        redacted = redact_secrets(
            "startup failed with sk-env-secret but kept /usr/bin visible",
            env={"OPENAI_API_KEY": "sk-env-secret", "PATH": "/usr/bin"},
        )

        self.assertNotIn("sk-env-secret", redacted)
        self.assertIn("<redacted>", redacted)
        self.assertIn("/usr/bin", redacted)


if __name__ == "__main__":
    unittest.main()
