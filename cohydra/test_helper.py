import os
import tempfile


class SrcDstDirMixin():
  """Fixture mixin for tests that need source and destination dirs.

  TODO: Make this class catch unexpected writes to the source
  directory.
  """

  def setUp(self):
    self.__src = tempfile.TemporaryDirectory()
    self.__dst = tempfile.TemporaryDirectory()

  def tearDown(self):
    self.__src.cleanup()
    self.__dst.cleanup()

  def src_path(self):
    return self.__src.name

  def dst_path(self):
    return self.__dst.name


def get_preserved_attrs(filename):
  """Get what should be preserved when a file/dir is unchanged.
  """

  stat = os.lstat(filename)
  return (stat.st_mode, stat.st_mtime)

def symlink_pointee_abspath(filename):
  """Get the abspath of what's pointed to by the given symlink.
  """

  return os.path.abspath(os.path.join(
    os.path.dirname(filename),
    os.readlink(filename)))
