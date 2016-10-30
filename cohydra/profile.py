import abc
import logging
import os

import six


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
