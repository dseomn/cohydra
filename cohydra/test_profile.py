import os
import tempfile
import unittest
import unittest.mock

from . import profile
from . import test_helper


@unittest.mock.patch.object(
  profile.Profile,
  'generate',
  autospec=True,
  )
@unittest.mock.patch.object(
  profile.Profile,
  '__abstractmethods__',
  new=set(),
  )
class TestProfile(unittest.TestCase):
  def setUp(self):
    self.dir = tempfile.TemporaryDirectory()

  def tearDown(self):
    self.dir.cleanup()

  def test_generate_all(self, mock_generate):
    p = profile.Profile(self.dir.name, None)
    p0 = profile.Profile(self.dir.name, p)
    p00 = profile.Profile(self.dir.name, p0)
    p1 = profile.Profile(self.dir.name, p)

    p.generate_all()

    self.assertEqual(
      mock_generate.mock_calls,
      [unittest.mock.call(x) for x in (p, p0, p00, p1)])


class TestFilterProfile(
    unittest.TestCase,
    test_helper.SrcDstDirMixin,
    ):
  def setUp(self):
    test_helper.SrcDstDirMixin.setUp(self)

  def tearDown(self):
    test_helper.SrcDstDirMixin.tearDown(self)

  def test_clean_ok(self):
    os.mkdir(os.path.join(self.dst_path(), 'dir'))
    os.mkdir(os.path.join(self.dst_path(), 'dir', 'dir'))
    os.symlink(
      '/dev/null',
      os.path.join(self.dst_path(), 'dir', 'dir', 'file'))
    os.symlink(
      '/dev/null',
      os.path.join(self.dst_path(), 'file'))
    self.assertNotEqual(os.listdir(self.dst_path()), [])

    root = profile.RootProfile(top_dir=self.src_path())
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=lambda profile, dir, contents: contents,
      )
    p.generate()

    self.assertEqual(os.listdir(self.dst_path()), [])

  def test_clean_error_file(self):
    open(os.path.join(self.dst_path(), 'file'), 'w').close()

    root = profile.RootProfile(top_dir=self.src_path())
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=lambda profile, dir, contents: contents,
      )

    self.assertRaisesRegex(
      RuntimeError,
      '^Cannot clean ',
      p.generate,
      )

    self.assertTrue(os.path.isfile(
      os.path.join(self.dst_path(), 'file')))

  def test_empty_noop(self):
    root = profile.RootProfile(top_dir=self.src_path())

    select_cb = unittest.mock.Mock(return_value=[])
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=select_cb,
      )

    p.generate()

    select_cb.assert_called_once_with(p, '', [])

    self.assertEqual(os.listdir(self.dst_path()), [])

  def test_select_none(self):
    os.mkdir(os.path.join(self.src_path(), 'dir'))
    os.mkdir(os.path.join(self.src_path(), 'dir', 'dir'))
    open(os.path.join(self.src_path(), 'dir', 'dir', 'file'), 'w').close()
    open(os.path.join(self.src_path(), 'file'), 'w').close()

    root = profile.RootProfile(top_dir=self.src_path())

    select_cb = unittest.mock.Mock(return_value=[])
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=select_cb,
      )

    p.generate()

    select_cb.assert_called_once_with(p, '', unittest.mock.ANY)

    self.assertEqual(os.listdir(self.dst_path()), [])

  def test_select_all(self):
    os.mkdir(os.path.join(self.src_path(), 'dir'))
    os.mkdir(os.path.join(self.src_path(), 'dir', 'dir'))
    open(os.path.join(self.src_path(), 'dir', 'dir', 'file'), 'w').close()
    open(os.path.join(self.src_path(), 'file'), 'w').close()

    root = profile.RootProfile(top_dir=self.src_path())

    select_cb = unittest.mock.Mock(
      wraps=lambda profile, dir, contents: contents)
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=select_cb,
      )

    p.generate()

    self.assertEqual(
      select_cb.mock_calls,
      [
        unittest.mock.call(p, '', unittest.mock.ANY),
        unittest.mock.call(p, 'dir', unittest.mock.ANY),
        unittest.mock.call(p, 'dir/dir', unittest.mock.ANY),
        ],
      )

    self.assertEqual(
      frozenset(os.listdir(self.dst_path())),
      {'dir', 'file'})
    self.assertEqual(
      frozenset(os.listdir(os.path.join(self.src_path(), 'dir'))),
      {'dir'})
    self.assertEqual(
      frozenset(os.listdir(os.path.join(self.src_path(), 'dir', 'dir'))),
      {'file'})

    self.assertEqual(
      test_helper.get_preserved_attrs(
        os.path.join(self.src_path(), 'dir')),
      test_helper.get_preserved_attrs(
        os.path.join(self.dst_path(), 'dir')),
      )
    self.assertEqual(
      test_helper.get_preserved_attrs(
        os.path.join(self.src_path(), 'dir', 'dir')),
      test_helper.get_preserved_attrs(
        os.path.join(self.dst_path(), 'dir', 'dir')),
      )

    self.assertEqual(
      test_helper.symlink_pointee_abspath(
        os.path.join(self.dst_path(), 'file')),
      os.path.abspath(
        os.path.join(self.src_path(), 'file')),
      )
    self.assertEqual(
      test_helper.symlink_pointee_abspath(
        os.path.join(self.dst_path(), 'dir', 'dir', 'file')),
      os.path.abspath(
        os.path.join(self.src_path(), 'dir', 'dir', 'file')),
      )

  def test_select_dir_but_not_its_contents(self):
    os.mkdir(os.path.join(self.src_path(), 'dir'))
    open(os.path.join(self.src_path(), 'dir', 'file'), 'w').close()

    root = profile.RootProfile(top_dir=self.src_path())

    select_cb = unittest.mock.Mock(
      wraps=lambda profile, dir, contents:
        contents if dir == '' else [],
      )
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=select_cb,
      )

    p.generate()

    self.assertEqual(
      select_cb.mock_calls,
      [
        unittest.mock.call(p, '', unittest.mock.ANY),
        unittest.mock.call(p, 'dir', unittest.mock.ANY),
        ],
      )

    self.assertEqual(os.listdir(self.dst_path()), [])

  def test_rename(self):
    open(os.path.join(self.src_path(), 'file'), 'w').close()

    root = profile.RootProfile(top_dir=self.src_path())

    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=
        lambda profile, dir, contents:
          [(x, 'renamed') for x in contents],
      )

    p.generate()

    self.assertEqual(os.listdir(self.dst_path()), ['renamed'])

    self.assertEqual(
      test_helper.symlink_pointee_abspath(
        os.path.join(self.dst_path(), 'renamed')),
      os.path.abspath(
        os.path.join(self.src_path(), 'file')),
      )

  def test_rename_dir_error(self):
    os.mkdir(os.path.join(self.src_path(), 'dir'))

    root = profile.RootProfile(top_dir=self.src_path())

    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=
        lambda profile, dir, contents:
          [(x, 'renamed') for x in contents],
      )

    self.assertRaisesRegex(
      NotImplementedError,
      '^Renaming directories is not supported: ',
      p.generate,
      )

  def test_rename_across_dir_error(self):
    os.mkdir(os.path.join(self.src_path(), 'dir'))
    open(os.path.join(self.src_path(), 'file'), 'w').close()

    root = profile.RootProfile(top_dir=self.src_path())

    def select_cb(profile, dir, contents):
      ret = []
      for entry in contents:
        if entry.name.endswith('file'):
          ret.append((entry, 'dir/file'))
        else:
          ret.append(entry)
      return ret
    p = profile.FilterProfile(
      top_dir=self.dst_path(),
      parent=root,
      select_cb=select_cb,
      )

    self.assertRaisesRegex(
      NotImplementedError,
      '^Renaming across dirs is not supported: ',
      p.generate,
      )
