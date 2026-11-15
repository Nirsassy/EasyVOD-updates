import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from content import CHANNEL_ID, CHANNEL_DESCRIPTION, announcement, welcome
from publish import PublicationError, State, Telegram, publish_verified, validate_manifest


class Fixture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        payload = b'APK fixture'
        for name in ('EasyVOD-1.2.3.apk', 'EasyVOD.apk'):
            (self.root / name).write_bytes(payload)
        self.manifest = {'schema': 1, 'applicationId': 'il.idanplus', 'versionName': '1.2.3',
            'versionCode': 123, 'minSdk': 23, 'sizeBytes': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest(), 'notes': 'תיקוני צפייה <script>&',
            'apkUrl': 'https://github.com/Nirsassy/EasyVOD-updates/releases/download/v1.2.3/EasyVOD-1.2.3.apk'}
        self.release = {'id': 7, 'tag_name': 'v1.2.3', 'draft': False, 'prerelease': False,
            'assets': [{'name': name, 'state': 'uploaded', 'size': len(payload)} for name in ('EasyVOD-1.2.3.apk', 'EasyVOD.apk')]}


class ReleaseValidation(Fixture):
    def test_both_published_apks_are_verified(self):
        validate_manifest(self.manifest, self.release, self.root)

    def test_corrupted_downloader_alias_blocks_publication(self):
        (self.root / 'EasyVOD.apk').write_bytes(b'wrong APK')
        with self.assertRaises(PublicationError):
            validate_manifest(self.manifest, self.release, self.root)

    def test_wrong_app_or_external_download_is_rejected(self):
        for key, value in (('applicationId', 'different.app'), ('apkUrl', 'https://example.org/app.apk'), ('versionCode', True), ('sha256', 'not-a-digest')):
            manifest = dict(self.manifest, **{key: value})
            with self.subTest(key=key), self.assertRaises(PublicationError):
                validate_manifest(manifest, self.release, self.root)

    def test_unpublished_prerelease_or_incomplete_release_is_rejected(self):
        for changes in ({'draft': True}, {'prerelease': True}, {'tag_name': 'v9.0.0'}, {'assets': []}):
            with self.subTest(changes=changes), self.assertRaises(PublicationError):
                validate_manifest(self.manifest, dict(self.release, **changes), self.root)

    def test_notes_are_escaped_and_bounded(self):
        message = announcement(self.manifest, 42)
        self.assertNotIn('<script>', message['text'])
        self.assertIn('&lt;script&gt;&amp;', message['text'])
        message = announcement(dict(self.manifest, notes='&' * 4000), 42)
        self.assertLess(len(message['text'].replace('&amp;', '&')), 4096)
        self.assertEqual(self.manifest['apkUrl'], message['reply_markup']['inline_keyboard'][0][0]['url'])

    def test_landing_contains_current_version_and_tv_installation(self):
        message = welcome(self.manifest)
        for text in ('1.2.3', '7197499', 'Downloader by AFTVnews', 'English', 'אין צורך להסיר'):
            self.assertIn(text, message['text'])
        self.assertLess(len(message['text']), 4096)
        self.assertLessEqual(len(CHANNEL_DESCRIPTION), 255)


class FakeStore:
    def __init__(self):
        self.state = {'schema': 1, 'channel_id': CHANNEL_ID, 'releases': {}}
        self.writes = []
        self.fail_save = False

    def load(self):
        return copy.deepcopy(self.state)

    def save(self, value):
        if self.fail_save:
            raise PublicationError('GitHub unavailable')
        self.state = copy.deepcopy(value)
        self.writes.append(copy.deepcopy(value))


class FakeTelegram:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.fail_send = False
        self.fail_edit = False

    def call(self, method, **parameters):
        assert parameters['chat_id'] == CHANNEL_ID
        self.calls.append(method)
        if method == 'sendMessage':
            assert self.store.state['releases']['v1.2.3']['status'] == 'pending'
            if self.fail_send:
                raise PublicationError('Ambiguous Telegram timeout')
            return {'message_id': 99, 'chat': {'id': CHANNEL_ID}}
        if method == 'editMessageText' and self.fail_edit:
            raise PublicationError('Temporary edit failure')
        return True


class PublishingBehavior(Fixture):
    def setUp(self):
        super().setUp()
        self.store = FakeStore()
        self.telegram = FakeTelegram(self.store)

    def publish(self):
        return publish_verified(self.manifest, self.release, self.telegram, self.store, 42)

    def test_success_records_message_and_updates_pinned_landing(self):
        result = self.publish()
        self.assertEqual(['sendMessage', 'editMessageText', 'pinChatMessage'], self.telegram.calls)
        self.assertEqual('pending', self.store.writes[0]['releases']['v1.2.3']['status'])
        self.assertEqual('sent', self.store.state['releases']['v1.2.3']['status'])
        self.assertEqual(99, result['message_id'])

    def test_rerun_edits_landing_without_duplicate_announcement(self):
        self.publish()
        self.publish()
        self.assertEqual(1, self.telegram.calls.count('sendMessage'))
        self.assertEqual(2, self.telegram.calls.count('editMessageText'))

    def test_ambiguous_timeout_stays_pending_and_cannot_resend(self):
        self.telegram.fail_send = True
        with self.assertRaises(PublicationError):
            self.publish()
        self.telegram.fail_send = False
        with self.assertRaises(PublicationError):
            self.publish()
        self.assertEqual(1, self.telegram.calls.count('sendMessage'))
        self.assertEqual('pending', self.store.state['releases']['v1.2.3']['status'])

    def test_failed_reservation_never_sends(self):
        self.store.fail_save = True
        with self.assertRaises(PublicationError):
            self.publish()
        self.assertNotIn('sendMessage', self.telegram.calls)

    def test_landing_failure_can_be_retried_without_resending(self):
        self.telegram.fail_edit = True
        with self.assertRaises(PublicationError):
            self.publish()
        self.telegram.fail_edit = False
        self.publish()
        self.assertEqual(1, self.telegram.calls.count('sendMessage'))

    def test_changed_release_identity_is_rejected(self):
        self.publish()
        self.release['id'] = 8
        with self.assertRaises(PublicationError):
            self.publish()
        self.assertEqual(1, self.telegram.calls.count('sendMessage'))

    def test_other_chats_and_polling_are_blocked_before_http(self):
        telegram = Telegram('123456:' + 'a' * 35)
        with patch('publish.urlopen') as network:
            for method, parameters in (('sendMessage', {'chat_id': 1}), ('getUpdates', {}), ('getChat', {'chat_id': '@someoneelse'})):
                with self.subTest(method=method), self.assertRaises(PublicationError):
                    telegram.call(method, **parameters)
            network.assert_not_called()

    def test_state_write_uses_compare_and_swap(self):
        store = State(); store.sha = 'expected-sha'
        with patch('publish.gh', return_value=json.dumps({'content': {'sha': 'next-sha'}})) as command:
            store.save(self.store.state)
        payload = json.loads(command.call_args.kwargs['input_value'])
        self.assertEqual('expected-sha', payload['sha'])
        self.assertEqual('main', payload['branch'])
        self.assertEqual('next-sha', store.sha)


if __name__ == '__main__':
    unittest.main()
