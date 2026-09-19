import unittest
from image_metadata import metadata


class ImageMetadataTests(unittest.TestCase):
    def setUp(self):
        self.config = {'version': '2.0.0', 'arch': ['amd64', 'aarch64'],
                       'options': {}, 'schema': {}, 'image': 'ghcr.io/holsteiner-kiel/ha-kuma-discovery'}

    def check(self, event, ref='refs/heads/main', repo='holsteiner-kiel/ha-kuma-discovery', **kw):
        return metadata(self.config, event, ref, repo, **kw)

    def test_release_strips_v_by_using_app_version(self):
        self.assertEqual(self.check('release', release_tag='v2.0.0'), ('2.0.0', True))
        with self.assertRaises(ValueError):
            self.check('release', release_tag='v2.0.1')

    def test_pr_and_fork_cannot_publish(self):
        self.assertFalse(self.check('pull_request', request_publish='true')[1])
        self.assertFalse(self.check('release', repo='example/fork', release_tag='v2.0.0')[1])

    def test_dispatch_requires_explicit_opt_in_on_main(self):
        self.assertFalse(self.check('workflow_dispatch')[1])
        self.assertTrue(self.check('workflow_dispatch', request_publish='true')[1])
        self.assertFalse(self.check('workflow_dispatch', ref='refs/heads/other', request_publish='true')[1])

    def test_branch_pushes_cannot_publish(self):
        self.assertFalse(self.check('push')[1])
        self.assertFalse(self.check('push', ref='refs/heads/release/2.0.0')[1])

    def test_invalid_metadata_fails_closed(self):
        for key, value in [('version', 'latest'), ('arch', ['amd64']), ('schema', {'extra': 'str'})]:
            original = self.config[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.config[key] = value
                self.check('push')
            self.config[key] = original
