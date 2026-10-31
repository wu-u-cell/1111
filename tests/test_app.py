import tempfile
import unittest
from pathlib import Path
from datetime import datetime
import sys
import subprocess
from contextlib import closing
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.con = app.connect(self.path)
        app.save_task(self.con, '交报告', '2030-01-02 12:00', 60, now=datetime(2030, 1, 1))
        self.now = datetime(2030, 1, 2, 11, 1)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def test_persistence_and_boundary(self):
        with closing(app.connect(self.path)) as other:
            self.assertEqual(other.execute('SELECT title FROM tasks').fetchone()[0], '交报告')
        self.assertEqual(len(app.pending(self.con, datetime(2030, 1, 2, 10, 59))), 0)
        self.assertEqual(len(app.pending(self.con, datetime(2030, 1, 2, 11))), 1)

    def test_deliver_only_once(self):
        calls = []
        def notify(rows):
            calls.append(len(rows))
            return True
        app.remind_once(self.con, notify, self.now)
        app.remind_once(self.con, notify, self.now)
        self.assertEqual(calls, [1])

    def test_failed_notification_retries(self):
        app.remind_once(self.con, lambda rows: False, self.now)
        self.assertEqual(len(app.pending(self.con, self.now)), 1)

    def test_completed_does_not_notify(self):
        with self.con:
            self.con.execute('UPDATE tasks SET done=1')
        self.assertEqual(app.pending(self.con, self.now), [])

    def test_mute_and_catchup(self):
        with self.con:
            self.con.execute("INSERT INTO settings VALUES('muted','1')")
        self.assertEqual(app.pending(self.con, self.now), [])
        with self.con:
            self.con.execute("UPDATE settings SET value='0'")
        self.assertEqual(len(app.pending(self.con, self.now)), 1)

    def test_no_deadline_and_invalid_time(self):
        app.save_task(self.con, '散步', '', None)
        self.assertEqual(len(app.pending(self.con, self.now)), 1)
        with self.assertRaises(ValueError):
            app.save_task(self.con, '', '', None)
        with self.assertRaises(ValueError):
            app.save_task(self.con, '过去', '2020-01-01 12:00', 0)

    def test_edit_rearms_notification(self):
        row = self.con.execute('SELECT * FROM tasks').fetchone()
        app.remind_once(self.con, lambda rows: True, self.now)
        app.save_task(self.con, '更新报告', '2030-01-03 12:00', 0, row['id'], now=self.now)
        self.assertEqual(app.pending(self.con, self.now), [])
        self.assertEqual(len(app.pending(self.con, datetime(2030,1,3,12))), 1)


class PrivacyTests(unittest.TestCase):
    def test_personal_storage_is_outside_repository(self):
        root = Path(app.__file__).resolve().parent
        self.assertFalse(app.DATA.resolve().is_relative_to(root))
        self.assertFalse(app.DB.resolve().is_relative_to(root))

    def test_unlisted_personal_files_are_ignored(self):
        root = Path(app.__file__).resolve().parent
        paths = ['diary.txt', 'personal.pdf', 'desktop.json', 'assistant.sqlite3',
                 '.env', 'backup/tasks.json', 'ui/private.json', 'tests/private.csv']
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin', '-z'],
                                cwd=root, input=('\0'.join(paths)+'\0').encode(),
                                capture_output=True, check=True)
        self.assertEqual(set(result.stdout.decode().rstrip('\0').split('\0')), set(paths))


class NewsTests(unittest.TestCase):
    def test_feed_deduplicates_rejects_script_and_sorts(self):
        data = b'''<rss><channel>
        <item><title>Older</title><link>https://example.com/old</link><pubDate>Wed, 01 Jan 2025 12:00:00 GMT</pubDate></item>
        <item><title>New &amp; safe</title><link>https://example.com/new</link><pubDate>Thu, 02 Jan 2025 12:00:00 GMT</pubDate></item>
        <item><title>Duplicate</title><link>https://example.com/new</link></item>
        <item><title>Bad</title><link>javascript:alert(1)</link></item>
        </channel></rss>'''
        items = app.parse_feed(data)
        self.assertEqual([i['title'] for i in items], ['New & safe', 'Older'])

    def test_missing_date_and_empty_feed(self):
        items = app.parse_feed(b'<rss><item><title>News</title><link>https://example.com</link></item></rss>')
        self.assertEqual(items[0]['date'], '来源未提供时间')
        self.assertEqual(app.parse_feed(b'<rss/>'), [])


if __name__ == '__main__':
    unittest.main()
