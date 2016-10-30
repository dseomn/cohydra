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
    top_dir: Where this profile's files will be stored.
    parent: The profile from which this profile is derived, or
        None for a root profile.
    children: List of child profiles.
  """

  def __init__(self, top_dir, parent):
    """Create a profile.
    """

    self.top_dir = top_dir

    self.parent = parent

    self.children = []

    if self.parent is not None:
      self.parent.children.append(self)

  def __str__(self):
    return '%s.%s(top_dir=%r, parent=%r)' % (
      self.__class__.__module__,
      self.__class__.__name__,
      self.top_dir,
      None if self.parent is None else self.parent.top_dir,
      )

  def generate_all(self, depth=0):
    """Generate this profile and all of its children.
    """

    logging.info('%sGenerating %s', '  ' * depth, self)
    self.generate()

    # TODO: parallelize?
    for child in self.children:
      child.generate_all(depth + 1)

  def print_all(self, depth=0):
    """List all profiles, for debugging.
    """

    print('  ' * depth + str(self))

    for child in self.children:
      child.print_all(depth + 1)

  def log(self, level, msg, *args, **kwargs):
    """Log, with additional info about the profile.
    """

    logging.log(
      level,
      '%s: %s' % (self, msg),
      *args,
      **kwargs)

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
            arguments are (dir, contents). dir is a path relative to
            self.top_dir and self.parent.top_dir. contents is a list
            of os.DirEntry objects. The callback must return a list of
            files to keep, from contents. Directories in the keep-list
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

    self.filter_dir('')

  def clean(self, relpath):
    """Clean the contents of the target directory.

    This does not delete relpath itself, just its contents.
    """

    path = os.path.join(self.top_dir, relpath)
    for entry in os.scandir(path):
      if entry.is_symlink():
        self.log(logging.DEBUG, 'Deleting symlink %r', entry.path)
        os.remove(entry.path)
      elif entry.is_dir():
        self.clean(os.path.join(relpath, entry.name))
        self.log(logging.DEBUG, 'Deleting directory %r', entry.path)
        os.rmdir(entry.path)
      else:
        self.log(
          logging.ERROR,
          'Found non-symlink non-directory %r',
          entry.path,
          )
        raise RuntimeError('Cannot clean %r' % relpath)

  def filter_dir(self, relpath):
    """Filter a single directory, recursively.

    If any files are included in the filter, this will create the
    directory (if needed) and symlink the files. Otherwise, this will
    do nothing.
    """

    parent_path = os.path.join(self.parent.top_dir, relpath)
    path = os.path.join(self.top_dir, relpath)

    keep = self.select_cb(relpath, list(os.scandir(parent_path)))

    for entry in keep:
      entry_relpath = os.path.join(relpath, entry.name)

      if entry.is_dir():
        self.filter_dir(entry_relpath)
      else:
        os.makedirs(path, exist_ok=True)
        self.log(logging.DEBUG, 'Linking %r', entry_relpath)
        os.symlink(
          os.path.relpath(os.path.abspath(entry.path), path),
          os.path.join(path, entry.name),
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
            argument is a single filename relative to
            self.parent.top_dir. If the file should be converted, it
            returns a filename relative to self.top_dir of where the
            converted file should be placed. Otherwise, it returns
            None, and the file is symlinked with the same relative
            filename.
        convert_cb: Callback to convert a file. Its arguments (in
            order) are the original filename and the target filename.
            This callback must be thread-safe.
    """

    super(ConvertProfile, self).__init__(**kwargs)

    self.select_cb = select_cb

    self.convert_cb = convert_cb

  def generate(self):
    keep = self.convert()

    self.clean(keep)

  def convert(self):
    """Convert or symlink files.

    Returns:
        A set of paths relative to self.top_dir of all converted or
        symlinked files, and all directories.
    """

    keep = set()

    for old_relpath, new_relpath, convert \
        in self.select_and_symlink():
      keep.add(new_relpath)

      if not convert:
        continue

      old_path = os.path.join(self.parent.top_dir, old_relpath)
      new_path = os.path.join(self.top_dir, new_relpath)

      # TODO: paralellize?
      self.log(
        logging.DEBUG,
        'Converting %r to %r',
        old_relpath,
        new_relpath,
        )
      self.convert_cb(old_path, new_path)
      shutil.copystat(old_path, new_path)

    return keep

  def select_and_symlink(self):
    """Select which files to convert, and handle symlinks.

    This function selects wich files to convert, but does not do any
    conversion. It does create all the directories, and creates
    symlinks for files that are not to be converted.

    Returns:
        A generator of tuples. The first item in a tuple is the path
        relative to self.parent.top_dir of each file or directory. The
        second item is the target path relative to self.top_dir. The
        third is True if conversion is needed, False otherwise.
    """

    for relpath, entry \
        in util.recursive_scandir(
          self.parent.top_dir,
          dir_first=True,
          ):
      if entry.is_dir():
        os.makedirs(entry.path, exist_ok=True)
        yield relpath, relpath, False
        continue

      convert_relpath = self.select_cb(relpath)

      if convert_relpath is None:
        # Remove anything already in this profile, and replace it with
        # a symlink.

        symlink_path = os.path.join(self.top_dir, relpath)
        symlink_dirpath = os.path.dirname(symlink_path)

        if os.path.isdir(symlink_path) \
            and not os.path.islink(symlink_path):
          self.log(logging.DEBUG, 'Removing %r', relpath)
          shutil.rmtree(symlink_path)
        elif os.path.lexists(symlink_path):
          self.log(logging.DEBUG, 'Removing %r', relpath)
          os.remove(symlink_path)

        self.log(logging.DEBUG, 'Linking %r', relpath)
        os.symlink(
          os.path.relpath(
            os.path.abspath(entry.path),
            symlink_dirpath),
          symlink_path,
          )

        yield relpath, relpath, False

      else:
        # Test whether the converted file is up to date, and get rid
        # of it if not.

        convert_path = os.path.join(self.top_dir, convert_relpath)

        if not os.path.lexists(convert_path):
          yield relpath, convert_relpath, True
          continue

        orig_stat = os.stat(entry.path)
        orig_mtime = (orig_stat.st_mtime, orig_stat.st_mtime_ns)
        convert_stat = os.lstat(convert_path)
        convert_mtime = (convert_stat.st_mtime, convert_stat.st_mtime_ns)

        if stat.S_ISDIR(convert_stat.st_mode):
          self.log(logging.DEBUG, 'Removing %r', convert_relpath)
          shutil.rmtree(convert_path)
          yield relpath, convert_relpath, True
        elif stat.S_ISREG(convert_stat.st_mode) \
            and orig_mtime == convert_mtime:
          self.log(logging.DEBUG, 'Up-to-date %r', convert_relpath)
          yield relpath, convert_relpath, False
        else:
          self.log(logging.DEBUG, 'Removing %r', convert_relpath)
          os.remove(convert_path)
          yield relpath, convert_relpath, True

  def clean(self, keep):
    """Clean self.top_dir.

    Delete everything in self.top_dir, except for the specified files.

    Args:
        keep: A set of paths relative to self.top_dir that should not
            be deleted.
    """

    for relpath, entry \
        in util.recursive_scandir(self.top_dir, dir_first=False):
      entry_relpath = os.path.join(relpath, entry.name)

      if entry_relpath not in keep:
        self.log(logging.DEBUG, 'Removing %r', entry.path)
        if os.path.isdir(entry.path) \
            and not os.path.islink(entry.path):
          os.rmdir(entry.path)
        else:
          os.remove(entry.path)
