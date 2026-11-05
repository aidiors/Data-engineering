import unittest
import uuid

from kazoo.exceptions import BadVersionError

from src.coordinator import claim
from src.receiver import publish
from src.zk_common import ROOT, client, immutable


class ReceiverIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.zk = client()
        self.base = '/hw4/integration-' + uuid.uuid4().hex
        self.zk.ensure_path(self.base)
        for key, data in [('epoch', b'0'), ('result', b'null'), ('publications', b'')]:
            self.zk.create(self.base + '/' + key, data)
        self.old = client()
        self.new = client()
        self.reference = immutable(ROOT / 'logs/test-objects', {'test': 'actual atomic transaction'})

    def tearDown(self):
        for zk in (self.old, self.new):
            zk.stop()
            zk.close()
        self.zk.delete(self.base, recursive=True)
        self.zk.stop()
        self.zk.close()

    def test_epoch_advance_rejects_old_writer_without_partial_publication(self):
        first_epoch = claim(self.old, self.base, 'A')
        self.old.stop()
        self.old.close()
        second_epoch = claim(self.new, self.base, 'B')
        self.assertGreater(second_epoch, first_epoch)
        self.assertEqual(publish(self.zk, self.base, {'coordinator': 'B', 'epoch': second_epoch, 'result': self.reference}, True), 1)
        before = self.zk.get(self.base + '/result')
        with self.assertRaises(BadVersionError):
            publish(self.zk, self.base, {'coordinator': 'A', 'epoch': first_epoch, 'result': self.reference}, True)
        after = self.zk.get(self.base + '/result')
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1].version, after[1].version)
        self.assertEqual(len(self.zk.get_children(self.base + '/publications')), 1)

    def test_epoch_without_receiver_check_does_not_protect_the_pointer(self):
        epoch = claim(self.old, self.base, 'A')
        self.old.stop()
        self.old.close()
        newer = claim(self.new, self.base, 'B')
        publish(self.zk, self.base, {'coordinator': 'B', 'epoch': newer, 'result': self.reference}, False)
        version = publish(self.zk, self.base, {'coordinator': 'A', 'epoch': epoch, 'result': self.reference}, False)
        self.assertEqual(version, 2)
        self.assertEqual(len(self.zk.get_children(self.base + '/publications')), 2)


if __name__ == '__main__':
    unittest.main()
