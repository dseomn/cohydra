import abc
import logging

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
