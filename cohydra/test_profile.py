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

