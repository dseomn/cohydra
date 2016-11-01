import abc
import logging
import os
import shutil
import stat

import six

from . import util


class Profile(six.with_metaclass(abc.ABCMeta)):
  """Base class for all collection profiles.

  Attributes:
    _top_dir: Where this profile's files will be stored. In general,
        this should not be used by subclasses. Instead, use dst_path
        and src_path to avoid accidentally writing to the parent's
        _top_dir.
    _parent: The profile from which this profile is derived, or
        None for a root profile.
    _children: List of child profiles.
  """

  def __init__(self, top_dir, parent):
    """Create a profile.
    """

    self._top_dir = top_dir

    self._parent = parent

    self._children = []

    if self._parent is not None:
      self._parent._children.append(self)

  def __str__(self):
    return '%s.%s(top_dir=%r, parent=%r)' % (
      self.__class__.__module__,
      self.__class__.__name__,
      self._top_dir,
      None if self._parent is None else self._parent._top_dir,
      )

  def generate_all(self, depth=0):
    """Generate this profile and all of its children.
    """

    logging.info('%sGenerating %s', '  ' * depth, self)
    self.generate()

    # TODO: parallelize?
    for child in self._children:
      child.generate_all(depth + 1)

  def print_all(self, depth=0):
    """List all profiles, for debugging.
    """

    print('  ' * depth + str(self))

    for child in self._children:
      child.print_all(depth + 1)

  def log(self, level, msg, *args, **kwargs):
    """Log, with additional info about the profile.
    """

    logging.log(
      level,
      '%s: %s' % (self, msg),
      *args,
      **kwargs)

  def src_path(self, relpath=''):
    """Given a relative path, return the absolute path for reading.

    This (very trivial) function is intended to make it obvious to a
    programmer when a filename is intended to be used for reading, to
    avoid accidental reads from self._top_dir.

    Args:
        relpath: Path, relative to self._parent._top_dir.

    Returns:
        An absolute path under self._parent._top_dir.
    """

    if self._parent is None:
      raise RuntimeError('Cannot read for %s' % self)

    return os.path.abspath(
      os.path.join(self._parent._top_dir, relpath))

  def dst_path(self, relpath=''):
    """Given a relative path, return the absolute path for writing.

    This (very trivial) function is intended to make it obvious to a
    programmer when a filename is intended to be used for writing, to
    avoid accidental writes to self._parent._top_dir, which could
    cause loss of important files.

    Args:
        relpath: Path, relative to self._top_dir.

    Returns:
        An absolute path under self._top_dir.
    """

    return os.path.abspath(os.path.join(self._top_dir, relpath))

  @abc.abstractmethod
  def generate(self):
    """Generate this profile from its parent.

    This method assumes that the parent is up-to-date.
    """

    pass


class RootProfile(Profile):
  """Root profile.

  This is a profile that consists of a directory with original files,
  instead of a profile derived from another profile's files.
  """

  def __init__(self, top_dir):
    Profile.__init__(self, top_dir, None)

  def generate(self):
    pass


class FilterProfile(Profile):
  """Profile in which every file is either symlinked or ignored.

  No files are modified or renamed by this profile, only symlinked
  from the parent, or ignored.

  This is useful for making profiles with a subset of the parent
  profile's files.
  """

  def __init__(self, select_cb, **kwargs):
    """
    Args:
        select_cb: Callback to select which files/directories in a
            directory get symlinked and which are ignored. Its
            arguments are (dir, contents). dir is a relative (source
            or destination) path. contents is a list of os.DirEntry
            objects. The callback must return a list of files to keep,
            from contents. Directories in the keep-list are recursed
            into; anything else is symlinked. Anything not in the
            keep-list is ignored.
    """

    super(FilterProfile, self).__init__(**kwargs)

    self.select_cb = select_cb

  def generate(self):
    # Everything in the profile dir is going to be a symlink or
    # directory, so preserving files from a previous run shouldn't
    # help performance enough to be worth the complicated logic of
    # determining what's up to date.
    self.clean('')

    self.filter_dir('')

  def clean(self, relpath):
    """Clean the contents of the target directory.

    This does not delete relpath itself, just its contents.
    """

    dst_path = self.dst_path(relpath)
    for dst_entry in os.scandir(dst_path):
      if dst_entry.is_symlink():
        self.log(logging.DEBUG, 'Deleting symlink %r', dst_entry.path)
        os.remove(dst_entry.path)
      elif dst_entry.is_dir():
        self.clean(os.path.join(relpath, dst_entry.name))
        self.log(
          logging.DEBUG,
          'Deleting directory %r',
          dst_entry.path,
          )
        os.rmdir(dst_entry.path)
      else:
        self.log(
          logging.ERROR,
          'Found non-symlink non-directory %r',
          dst_entry.path,
          )
        raise RuntimeError('Cannot clean %r' % relpath)

  def filter_dir(self, relpath):
    """Filter a single directory, recursively.

    If any files are included in the filter, this will create the
    directory (if needed) and symlink the files. Otherwise, this will
    do nothing.
    """

    src_path = self.src_path(relpath)
    dst_path = self.dst_path(relpath)

    src_keep = self.select_cb(relpath, list(os.scandir(src_path)))

    for src_entry in src_keep:
      entry_relpath = os.path.join(relpath, src_entry.name)

      if src_entry.is_dir():
        self.filter_dir(entry_relpath)
      else:
        os.makedirs(dst_path, exist_ok=True)
        self.log(logging.DEBUG, 'Linking %r', entry_relpath)
        os.symlink(
          os.path.relpath(os.path.abspath(src_entry.path), dst_path),
          os.path.join(dst_path, src_entry.name),
          )


class ConvertProfile(Profile):
  """Profile in which every file is either symlinked or converted.

  Each directory is created. Each regular file (or symlink to a
  regular file) is either symlinked, or converted to another format.
  During conversion a new filename may be used (e.g., 'foo.flac.ogg'
  instead of 'foo.flac').

  This is useful for making profiles with the same files as the
  parent, but optimized for a different environment. E.g., recoded to
  take up less disk space, or to use only formats supported by a
  particular device.
  """

  def __init__(self, select_cb, convert_cb, **kwargs):
    """
    Args:
        select_cb: Callback to select which files to convert. Its
            argument is a single relative source filename. If the file
            should be converted, it returns a relative destination
            filename of where the converted file should be placed.
            Otherwise, it returns None, and the file is symlinked with
            the same relative filename.
        convert_cb: Callback to convert a file. Its arguments (in
            order) are the source filename and the destination
            filename. This callback must be thread-safe.
    """

    super(ConvertProfile, self).__init__(**kwargs)

    self.select_cb = select_cb

    self.convert_cb = convert_cb

  def generate(self):
    dst_keep = self.convert()

    self.clean(dst_keep)

  def convert(self):
    """Convert or symlink files.

    Returns:
        A set of relative destination paths of all converted or
        symlinked files, and all directories.
    """

    dst_keep = set()

    for src_relpath, dst_relpath, convert \
        in self.select_and_symlink():
      dst_keep.add(dst_relpath)

      if not convert:
        continue

      src_path = self.src_path(src_relpath)
      dst_path = self.dst_path(dst_relpath)

      # TODO: paralellize?
      self.log(
        logging.DEBUG,
        'Converting %r to %r',
        src_relpath,
        dst_relpath,
        )
      self.convert_cb(src_path, dst_path)
      shutil.copystat(src_path, dst_path)

    return dst_keep

  def select_and_symlink(self):
    """Select which files to convert, and handle symlinks.

    This function selects wich files to convert, but does not do any
    conversion. It does create all the directories, and creates
    symlinks for files that are not to be converted.

    Returns:
        A generator of tuples. The first item in a tuple is the
        relative source path of each file or directory. The second
        item is the relative destination path. The third is True if
        conversion is needed, False otherwise.
    """

    for src_relpath, src_entry \
        in util.recursive_scandir(
          self.src_path(),
          dir_first=True,
          ):
      if src_entry.is_dir():
        os.makedirs(src_entry.path, exist_ok=True)
        yield src_relpath, src_relpath, False
        continue

      dst_relpath = self.select_cb(src_relpath)

      if dst_relpath is None:
        # Remove anything already in this profile, and replace it with
        # a symlink.

        dst_relpath = src_relpath
        dst_path = self.dst_path(dst_relpath)
        dst_dirpath = os.path.dirname(dst_path)

        if os.path.isdir(dst_path) \
            and not os.path.islink(dst_path):
          self.log(logging.DEBUG, 'Removing %r', dst_relpath)
          shutil.rmtree(dst_path)
        elif os.path.lexists(dst_path):
          self.log(logging.DEBUG, 'Removing %r', dst_relpath)
          os.remove(dst_path)

        self.log(logging.DEBUG, 'Linking %r', dst_relpath)
        os.symlink(
          os.path.relpath(
            os.path.abspath(src_entry.path),
            dst_dirpath),
          dst_path,
          )

        yield src_relpath, dst_relpath, False

      else:
        # Test whether the converted file is up to date, and get rid
        # of it if not.

        dst_path = self.dst_path(dst_relpath)

        if not os.path.lexists(dst_path):
          yield src_relpath, dst_relpath, True
          continue

        src_stat = os.stat(src_entry.path)
        src_mtime = (src_stat.st_mtime, src_stat.st_mtime_ns)
        dst_stat = os.lstat(dst_path)
        dst_mtime = (dst_stat.st_mtime, dst_stat.st_mtime_ns)

        if stat.S_ISDIR(dst_stat.st_mode):
          self.log(logging.DEBUG, 'Removing %r', dst_relpath)
          shutil.rmtree(dst_path)
          yield src_relpath, dst_relpath, True
        elif stat.S_ISREG(dst_stat.st_mode) \
            and src_mtime == dst_mtime:
          self.log(logging.DEBUG, 'Up-to-date %r', dst_relpath)
          yield src_relpath, dst_relpath, False
        else:
          self.log(logging.DEBUG, 'Removing %r', dst_relpath)
          os.remove(dst_path)
          yield src_relpath, dst_relpath, True

  def clean(self, dst_keep):
    """Clean the destination directory.

    Delete everything in dst_path(), except for the specified files.

    Args:
        dst_keep: A set of relative destination paths that should not
            be deleted.
    """

    for dst_relpath, dst_entry \
        in util.recursive_scandir(self.dst_path(), dir_first=False):
      dst_entry_relpath = os.path.join(dst_relpath, dst_entry.name)

      if dst_entry_relpath not in dst_keep:
        self.log(logging.DEBUG, 'Removing %r', dst_entry.path)
        if os.path.isdir(dst_entry.path) \
            and not os.path.islink(dst_entry.path):
          os.rmdir(dst_entry.path)
        else:
          os.remove(dst_entry.path)
