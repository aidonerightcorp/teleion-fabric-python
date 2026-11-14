# Teleion context: CHARTER.md sha256=6fe2bd046fd154952a79d25d81d1efcf8474ab4eabf034b105dcbe7b513e84ee; read AGENTS.md
"""Runtime version identifies the installed distribution."""
import importlib.metadata
import unittest
import teleion_fabric

class ReleaseVersion(unittest.TestCase):
    def test_runtime_matches_distribution(self):
        self.assertEqual(teleion_fabric.__version__, importlib.metadata.version('teleion-fabric'))
