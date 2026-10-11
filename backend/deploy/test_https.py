import tempfile
import unittest
from pathlib import Path

from configure_https import configure, https_config


class HTTPSConfigurationTests(unittest.TestCase):
    def test_production_defaults_secure_and_development_stays_http(self):
        self.assertEqual(https_config({"OJ_ENV": "production"}), {"mode": "direct", "proxies": [], "hsts_seconds": 3600})
        self.assertEqual(https_config({})["mode"], "off")
        self.assertEqual(https_config({})["hsts_seconds"], 0)

    def test_proxy_requires_explicit_bounded_networks(self):
        for value in ("", "0.0.0.0/0", "::/0", "proxy.example.com", "127.0.0.1; return 200;", "fe80::1%x;}/128"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                https_config({"OJ_HTTPS_MODE": "proxy", "OJ_TRUSTED_PROXY_CIDRS": value})
        self.assertEqual(https_config({"OJ_HTTPS_MODE": "proxy", "OJ_TRUSTED_PROXY_CIDRS": "192.0.2.10/32,2001:db8::1/128"})["proxies"],
                         ["192.0.2.10/32", "2001:db8::1/128"])

    def test_invalid_configuration_does_not_replace_previous_files(self):
        with tempfile.TemporaryDirectory() as directory:
            configure(directory, {"OJ_ENV": "production"})
            before = (Path(directory) / "https_protocol.conf").read_bytes()
            for environment in ({"OJ_HTTPS_MODE": "invalid"}, {"OJ_HSTS_SECONDS": "-1"}, {"OJ_HSTS_SECONDS": "31536001"},
                                {"OJ_HSTS_SECONDS": "3600; include bad.conf;"}, {"OJ_HTTPS_MODE": "proxy"}):
                with self.subTest(environment=environment), self.assertRaises(ValueError):
                    configure(directory, environment)
                self.assertEqual((Path(directory) / "https_protocol.conf").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
