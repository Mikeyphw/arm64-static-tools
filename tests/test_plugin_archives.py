"""Current plugin archive extraction security and upstream compatibility tests."""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ast_package_plugins', ROOT / 'scripts/package_plugins.py')
PKG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PKG)


def archive(*members):
    """Produce deterministic Git-like archives with regular, link and dir members."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as z:
        for typ, name, data in members:
            info = tarfile.TarInfo(name)
            info.mtime = 0
            if typ == 'file':
                raw = data.encode()
                info.mode = 0o644
                info.size = len(raw)
                z.addfile(info, io.BytesIO(raw))
            elif typ == 'link':
                info.type = tarfile.SYMTYPE
                info.linkname = data
                z.addfile(info)
            elif typ == 'hardlink':
                info.type = tarfile.LNKTYPE
                info.linkname = data
                z.addfile(info)
            elif typ == 'dir':
                info.type = tarfile.DIRTYPE
                z.addfile(info)
            else:
                raise AssertionError(typ)
    return buffer.getvalue()


class PluginArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dst = Path(self.temp.name) / 'stage'
        self.dst.mkdir()

    def extract(self, *members):
        return PKG.extract_plugin_archive(archive(*members), self.dst, 'test-plugin')

    def test_relative_documentation_link_is_regular_file(self):
        count = self.extract(
            ('dir', 'highlighters/', ''),
            ('dir', 'highlighters/main/', ''),
            ('dir', 'docs/', ''),
            ('dir', 'docs/highlighters/', ''),
            ('file', 'docs/highlighters/main.md', 'markdown contents\n'),
            ('link', 'highlighters/main/README.md', '../../docs/highlighters/main.md'),
        )
        self.assertEqual(count, 2)
        link = self.dst / 'highlighters/main/README.md'
        self.assertFalse(link.is_symlink())
        self.assertEqual(link.read_text(), 'markdown contents\n')
        self.assertEqual((self.dst / 'docs/highlighters/main.md').read_bytes(), link.read_bytes())

    def test_forward_reference_to_regular_file_is_safe(self):
        self.extract(('link', 'README.md', 'docs/file.md'),
                     ('dir', 'docs/', ''), ('file', 'docs/file.md', 'text'))
        self.assertEqual((self.dst / 'README.md').read_text(), 'text')

    def test_reject_external_relative_traversal(self):
        with self.assertRaisesRegex(ValueError, 'external archive link'):
            self.extract(('link', 'sub/README.md', '../../../etc/passwd'))
        self.assertFalse((Path(self.temp.name) / 'etc/passwd').exists())

    def test_reject_absolute_link(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive link'):
            self.extract(('link', 'README.md', '/etc/passwd'))

    def test_reject_dangling_link(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive link target'):
            self.extract(('link', 'README.md', 'no-such-file.md'))

    def test_reject_symlink_chain(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive link target'):
            self.extract(('file', 'file.md', 'hello'),
                         ('link', 'link-1.md', 'file.md'),
                         ('link', 'link-2.md', 'link-1.md'))

    def test_reject_link_to_directory(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive link target'):
            self.extract(('dir', 'docs/', ''), ('link', 'link.md', 'docs'))

    def test_reject_hardlink(self):
        with self.assertRaisesRegex(ValueError, 'unsupported archive entry'):
            self.extract(('file', 'file', 'safe'), ('hardlink', 'hard', 'file'))

    def test_reject_path_traversal(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive entry'):
            self.extract(('file', '../outside', 'unsafe'))
        self.assertFalse((Path(self.temp.name) / 'outside').exists())

    def test_reject_duplicate_members(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive entry'):
            self.extract(('file', 'README', 'one'), ('file', 'README', 'two'))

    def test_reject_file_directory_collision(self):
        with self.assertRaisesRegex(ValueError, 'conflicting archive members'):
            self.extract(('file', 'docs', 'one'), ('file', 'docs/nested', 'two'))

    def test_reject_link_in_destination(self):
        (self.dst / 'docs').symlink_to(Path(self.temp.name))
        with self.assertRaisesRegex(ValueError, 'unsafe staging path'):
            self.extract(('dir', 'docs/', ''), ('file', 'docs/file', 'one'))

    def test_reject_symlink_as_output_root(self):
        other = Path(self.temp.name) / 'outside'
        other.mkdir()
        self.dst.rmdir()
        self.dst.symlink_to(other)
        with self.assertRaisesRegex(ValueError, 'unsafe output directory'):
            self.extract(('file', 'README.md', 'safe'))

    def test_reject_windows_style_paths(self):
        with self.assertRaisesRegex(ValueError, 'unsafe archive entry'):
            self.extract(('file', 'dir\\evil', 'unsafe'))
        with self.assertRaisesRegex(ValueError, 'unsafe archive link'):
            self.extract(('file', 'safe', 'x'), ('link', 'README.md', '..\\safe'))

    def test_reject_oversized_member(self):
        with self.assertRaisesRegex(ValueError, 'oversized plugin file'):
            self.extract(('file', 'big', 'x' * 2_000_001))


if __name__ == '__main__':
    unittest.main()
