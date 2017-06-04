import os
import tempfile
import unittest

from . import profile
from . import test_helper
from . import util


class TestRecursiveScandir(unittest.TestCase):
  def setUp(self):
    self.dir = tempfile.TemporaryDirectory()

    # Make a tree with:
    #  * Dir with 1 file: /single-file
    #  * Dir with 1 dir: /single-dir
    #  * Empty dir: /single-dir/empty
    #  * Dir with both files and dirs: /
    self.paths = {
      'single-file',
      os.path.join('single-file', 'empty'),
      'single-dir',
      os.path.join('single-dir', 'empty'),
      'empty',
      }
    os.mkdir(os.path.join(self.dir.name, 'single-file'))
    open(os.path.join(self.dir.name, 'single-file', 'empty'), 'w') \
      .close()
    os.mkdir(os.path.join(self.dir.name, 'single-dir'))
    os.mkdir(os.path.join(self.dir.name, 'single-dir', 'empty'))
    open(os.path.join(self.dir.name, 'empty'), 'w').close()

  def tearDown(self):
    self.dir.cleanup()

  def test_entry_matches_path(self):
    for path, entry in util.recursive_scandir(self.dir.name):
      with self.subTest(path=path):
        self.assertEqual(
          os.path.join(self.dir.name, path),
          entry.path)

  def test_dir_first(self):
    paths = [
      path
      for path, entry
      in util.recursive_scandir(self.dir.name, dir_first=True)
      ]

    self.assertEqual(set(paths), self.paths)
    self.assertLess(
      paths.index('single-file'),
      paths.index(os.path.join('single-file', 'empty')))
    self.assertLess(
      paths.index('single-dir'),
      paths.index(os.path.join('single-dir', 'empty')))

  def test_dir_last(self):
    paths = [
      path
      for path, entry
      in util.recursive_scandir(self.dir.name, dir_first=False)
      ]

    self.assertEqual(set(paths), self.paths)
    self.assertGreater(
      paths.index('single-file'),
      paths.index(os.path.join('single-file', 'empty')))
    self.assertGreater(
      paths.index('single-dir'),
      paths.index(os.path.join('single-dir', 'empty')))


class TestFixDirStats(unittest.TestCase, test_helper.SrcDstDirMixin):
  class FixDirStatsProfile(profile.Profile):
    def generate(self):
      util.fix_dir_stats(self)

  def setUp(self):
    test_helper.SrcDstDirMixin.setUp(self)

    self.profile = TestFixDirStats.FixDirStatsProfile(
      self.dst_path(),
      profile.RootProfile(self.src_path()),
      )

  def tearDown(self):
    test_helper.SrcDstDirMixin.tearDown(self)

  def test_dir(self):
    src_dir = os.path.join(self.src_path(), 'foo')
    os.mkdir(src_dir, mode=0o555)
    os.utime(src_dir, (0, 0))

    dst_dir = os.path.join(self.dst_path(), 'foo')
    os.mkdir(dst_dir, mode=0o777)
    os.utime(dst_dir, (7, 7))

    self.assertNotEqual(
      test_helper.get_preserved_attrs(src_dir),
      test_helper.get_preserved_attrs(dst_dir),
      )

    self.profile.generate()

    self.assertEqual(
      test_helper.get_preserved_attrs(src_dir),
      test_helper.get_preserved_attrs(dst_dir),
      )
