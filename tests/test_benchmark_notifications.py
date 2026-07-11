import unittest
from unittest.mock import patch

from app.notify import send_benchmark_start_notification


class BenchmarkStartNotificationTest(unittest.TestCase):
    @patch('app.notify.requests.post')
    def test_discord_notification_describes_proxy_mode_and_paused_containers(self, post):
        post.return_value.raise_for_status.return_value = None

        send_benchmark_start_notification(
            sidecar_mode=False,
            paused_containers=['qbittorrent', 'sabnzbd'],
            discord_url='https://discord.example/webhook',
            lang='en',
        )

        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['embeds'][0]['title'], '🔵 Benchmark started')
        self.assertEqual(payload['embeds'][0]['fields'], [
            {'name': 'Mode', 'value': 'HTTP proxy', 'inline': True},
            {'name': 'Paused containers', 'value': 'qbittorrent, sabnzbd', 'inline': False},
        ])
        self.assertNotIn('content', payload)


if __name__ == '__main__':
    unittest.main()
