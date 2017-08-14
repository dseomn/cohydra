import abc
import logging
import multiprocessing
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

  No files are modified by this profile, only symlinked from the
  parent (possibly with a different filename), or ignored.

  This is useful for making profiles with a subset of the parent
  profile's files.
  """

  def __init__(self, select_cb, **kwargs):
    """
    Args:
        select_cb: Callback to select which files/directories in a
            directory get symlinked and which are ignored. Its
            arguments are (profile, src_relpath, dst_relpath,
            contents). src_relpath and dst_relpath are relative paths
            to the original directory name, and the possibly renamed
            directory name. contents is a list of os.DirEntry objects.
            The callback must return a list of files to keep, from
            contents. Optionally, items in the list may be tuples of
            the form (file from contents, new relative destination
            path), in which case the file is kept and renamed.
            (Currently, renaming is supported only within the same,
            possibly renamed, directory. I.e., the renamed filename
            must be within dst_relpath.) Directories in the keep-list
            are recursed into; anything else is symlinked. Anything
            not in the keep-list is ignored.
    """

    super(FilterProfile, self).__init__(**kwargs)

    self.select_cb = select_cb

  def generate(self):
    # Everything in the profile dir is going to be a symlink or
    # directory, so preserving files from a previous run shouldn't
    # help performance enough to be worth the complicated logic of
    # determining what's up to date.
    self.clean('')

    self.filter_dir('', '')

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

  def filter_dir(self, src_relpath, dst_relpath):
    """Filter a single directory, recursively.

    If any files are included in the filter, this will create the
    directory (if needed) and symlink the files. Otherwise, this will
    do nothing.
    """

    src_path = self.src_path(src_relpath)
    dst_path = self.dst_path(dst_relpath)

    src_keep = self.select_cb(
      self,
      src_relpath,
      dst_relpath,
      list(os.scandir(src_path)),
      )

    for src_entry in src_keep:
      if isinstance(src_entry, tuple):
        # Keep and rename.
        src_direntry, dst_entry_relpath = src_entry
        src_entry_relpath = os.path.join(src_relpath, src_direntry.name)
      else:
        # Keep, with same name in the same directory.
        src_direntry = src_entry
        src_entry_relpath = os.path.join(src_relpath, src_direntry.name)
        dst_entry_relpath = os.path.join(dst_relpath, src_direntry.name)

      if os.path.dirname(dst_entry_relpath) != dst_relpath:
        raise NotImplementedError(
          'Renaming across dirs is not supported: '
          '%r -> %r in directory %r -> %r' % (
            src_entry_relpath,
            dst_entry_relpath,
            src_relpath,
            dst_relpath,
            )
          )

      if src_direntry.is_dir():
        self.filter_dir(src_entry_relpath, dst_entry_relpath)
      else:
        os.makedirs(dst_path, exist_ok=True)
        self.log(
          logging.DEBUG,
          'Linking %r -> %r',
          dst_entry_relpath,
          src_entry_relpath,
          )
        os.symlink(
          os.path.relpath(self.src_path(src_entry_relpath), dst_path),
          self.dst_path(dst_entry_relpath),
          )

    if dst_relpath and os.path.isdir(dst_path):
      shutil.copystat(src_path, dst_path)


class ConvertProfile(Profile):
  """Profile in which every file is either symlinked or converted.

  Each directory is created. Each regular file (or symlink to a
  regular file) is either symlinked, or converted to another format.
  During conversion a new filename may be used (e.g., 'foo.flac.ogg'
  instead of 'foo.flac'), however no two source files may map (via
  symlinking or conversion) to the same destination filename.

  This is useful for making profiles with the same files as the
  parent, but optimized for a different environment. E.g., recoded to
  take up less disk space, or to use only formats supported by a
  particular device.
  """

  def __init__(self, select_cb, convert_cb, **kwargs):
    """
    Args:
        select_cb: Callback to select which files to convert. Its
            arguments (in order) are the profile, and a single
            relative source filename. If the file should be converted,
            it returns a relative destination filename of where the
            converted file should be placed.  Otherwise, it returns
            None, and the file is symlinked with the same relative
            filename. This callback must ensure that no two source
            files are mapped (via symlinking or conversion) to the
            same destination filename.
        convert_cb: Callback to convert a file. Its arguments (in
            order) are the profile, the source filename, and the
            destination filename. This callback must be
            multi-threading and multi-processing safe.
    """

    super(ConvertProfile, self).__init__(**kwargs)

    self.select_cb = select_cb

    self.convert_cb = convert_cb

  def generate(self):
    dst_keep = self.convert()

    self.clean(dst_keep)

    util.fix_dir_stats(self)

  def convert(self):
    """Convert or symlink files.

    Returns:
        A set of relative destination paths of all converted or
        symlinked files, and all directories.
    """

    # Map from dst relpath to src relpath.
    relpath_dst_to_src = {}

    with multiprocessing.Pool() as pool:
      results = []

      for src_relpath, dst_relpath, convert \
          in self.select_and_symlink():
        if dst_relpath in relpath_dst_to_src:
          self.log(
            logging.ERROR,
            'Found duplicate destination %r from sources %r and %r',
            dst_relpath,
            relpath_dst_to_src[dst_relpath],
            src_relpath,
            )
          raise RuntimeError(
            'Duplicate destination path %r' % dst_relpath)
        else:
          relpath_dst_to_src[dst_relpath] = src_relpath

        if not convert:
          continue

        results.append(
          pool.apply_async(
            self.convert_one,
            (src_relpath, dst_relpath),
            )
          )

      for result in results:
        result.get()

    return frozenset(relpath_dst_to_src.keys())

  def convert_one(self, src_relpath, dst_relpath):
    """Convert a single file.

    This function must be multi-threading and multi-processing safe.
    """

    src_path = self.src_path(src_relpath)
    dst_path = self.dst_path(dst_relpath)

    self.log(
      logging.DEBUG,
      'Converting %r to %r',
      src_relpath,
      dst_relpath,
      )
    self.convert_cb(self, src_path, dst_path)
    shutil.copystat(src_path, dst_path)

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
        dst_relpath = src_relpath
        dst_path = self.dst_path(dst_relpath)

        # Get rid of any non-directory where this directory should be.
        if os.path.lexists(dst_path):
          if not os.path.isdir(dst_path) or os.path.islink(dst_path):
            self.log(logging.DEBUG, 'Removing %r', dst_relpath)
            os.remove(dst_path)

        # Create the directory if needed.
        self.log(logging.DEBUG, 'Creating directory %r', dst_relpath)
        os.makedirs(dst_path, exist_ok=True)

        yield src_relpath, dst_relpath, False
        continue

      dst_relpath = self.select_cb(self, src_relpath)

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
      if dst_relpath not in dst_keep:
        self.log(logging.DEBUG, 'Removing %r', dst_entry.path)
        if os.path.isdir(dst_entry.path) \
            and not os.path.islink(dst_entry.path):
          os.rmdir(dst_entry.path)
        else:
          os.remove(dst_entry.path)


class SanitizeFilenameProfile(FilterProfile):
  """Profile to sanitize filenames.

  This is currently based on
  https://msdn.microsoft.com/en-us/library/aa365247.aspx.
  """

  # Map from forbidden characters to replacements.
  _forbidden_chars_map = {
    0x00: '',
    0x01: '',
    0x02: '',
    0x03: '',
    0x04: '',
    0x05: '',
    0x06: '',
    0x07: '',
    0x08: '',
    0x09: '_', # tab
    0x0A: '_', # line feed
    0x0B: '',
    0x0C: '',
    0x0D: '_', # carriage return
    0x0E: '',
    0x0F: '',
    0x10: '',
    0x11: '',
    0x12: '',
    0x13: '',
    0x14: '',
    0x15: '',
    0x16: '',
    0x17: '',
    0x18: '',
    0x19: '',
    0x1A: '',
    0x1B: '',
    0x1C: '',
    0x1D: '',
    0x1E: '',
    0x1F: '',
    ord('"'): '_',
    ord('*'): '_',
    ord('/'): '_',
    ord(':'): '_',
    ord('<'): '_',
    ord('>'): '_',
    ord('?'): '_',
    ord('\\'): '_',
    ord('|'): '_',
    }

  # Names that Windows has reserved.
  _reserved_names = {s.casefold() for s in [
    'CON',
    'PRN',
    'AUX',
    'NUL',
    'COM1',
    'COM2',
    'COM3',
    'COM4',
    'COM5',
    'COM6',
    'COM7',
    'COM8',
    'COM9',
    'LPT1',
    'LPT2',
    'LPT3',
    'LPT4',
    'LPT5',
    'LPT6',
    'LPT7',
    'LPT8',
    'LPT9',
    ]}

  def __init__(self, **kwargs):
    super(SanitizeFilenameProfile, self).__init__(
      select_cb=self._sanitize_cb,
      **kwargs,
      )

  def _sanitize_cb(self, profile, src_relpath, dst_relpath, contents):
    """select_cb for parent FilterProfile.
    """

    keep = []
    casefolded_names = set()
    for entry in contents:
      sanitized_name = self._sanitize_name(entry.name)
      sanitized_relpath = os.path.join(dst_relpath, sanitized_name)

      # Casefold when looking for duplicates, because some filesystems
      # are case-insensitive.
      casefolded_name = sanitized_name.casefold()
      if casefolded_name in casefolded_names:
        raise RuntimeError(
          'Sanitizing would create duplicate file: %r' % (
            sanitized_relpath,
            )
          )
      casefolded_names.add(casefolded_name)

      keep.append((entry, sanitized_relpath))

    return keep

  def _sanitize_name(self, filename):
    """Sanitize a single path component.
    """

    sanitized = filename.translate(
      SanitizeFilenameProfile._forbidden_chars_map)

    if sanitized in ('.', '..'):
      sanitized = sanitized + '_'

    basename, dot, extension = sanitized.partition('.')
    if basename.casefold() in SanitizeFilenameProfile._reserved_names:
      basename = basename + '_'
    sanitized = ''.join([basename, dot, extension])

    if sanitized and sanitized[-1] in '. ':
      sanitized = sanitized[:-1] + '_'

    return sanitized
