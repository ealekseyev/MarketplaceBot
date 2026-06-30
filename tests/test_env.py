from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fb_marketplace.env import facebook_credentials_from_env, load_env_file


class EnvTests(unittest.TestCase):
    def test_load_env_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "# comment\nFACEBOOK_EMAIL='seller@example.com'\nFACEBOOK_PASSWORD=secret\n",
                encoding="utf-8",
            )
            values = load_env_file(str(env_path))
            self.assertEqual(values["FACEBOOK_EMAIL"], "seller@example.com")
            self.assertEqual(values["FACEBOOK_PASSWORD"], "secret")

    def test_facebook_credentials_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "FACEBOOK_USERNAME=my-login\nFB_PASSWORD=topsecret\n",
                encoding="utf-8",
            )
            email, password = facebook_credentials_from_env(str(env_path))
            self.assertEqual(email, "my-login")
            self.assertEqual(password, "topsecret")


if __name__ == "__main__":
    unittest.main()
