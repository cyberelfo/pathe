import unittest
from unittest.mock import patch, mock_open, MagicMock
import json
import os
import sys

# Add script directory to sys.path to import pathe_checker
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pathe_checker

MOCK_HTML = """
<!DOCTYPE html>
<html>
<body>
    <script id="ng-state" type="application/json">
    {
        "show1": {
            "title": "Special Movie 1",
            "slug": "special-movie-1",
            "releaseAt": {
                "NL_NL": "2026-07-20"
            },
            "isEventSpecial": true,
            "genres": ["Action"]
        },
        "show2": {
            "title": "Regular Movie 2",
            "slug": "regular-movie-2",
            "releaseAt": {
                "NL_NL": "2026-07-21"
            },
            "isEventSpecial": false,
            "specialEvent": false,
            "genres": ["Comedy"]
        },
        "nested": {
            "show3": {
                "title": "Special Movie 3",
                "slug": "special-movie-3",
                "releaseAt": {
                    "NL_NL": "2026-07-22"
                },
                "specialEvent": true,
                "genres": ["Sci-Fi", "Drama"]
            }
        }
    }
    </script>
</body>
</html>
"""

class TestPatheChecker(unittest.TestCase):

    def test_find_shows_recursive(self):
        test_obj = {
            "level1": {
                "slug": "movie-1",
                "title": "Movie 1",
                "releaseAt": "2026-07-20",
                "other": "data"
            },
            "nested": [
                {
                    "slug": "movie-2",
                    "title": "Movie 2",
                    "releaseAt": "2026-07-21"
                }
            ]
        }
        shows = {}
        pathe_checker.find_shows_recursive(test_obj, shows)
        self.assertEqual(len(shows), 2)
        self.assertIn("movie-1", shows)
        self.assertIn("movie-2", shows)
        self.assertEqual(shows["movie-1"]["title"], "Movie 1")
        self.assertEqual(shows["movie-2"]["title"], "Movie 2")

    def test_parse_specials_from_html(self):
        specials = pathe_checker.parse_specials_from_html(MOCK_HTML)
        self.assertEqual(len(specials), 2)
        self.assertIn("special-movie-1", specials)
        self.assertIn("special-movie-3", specials)
        self.assertNotIn("regular-movie-2", specials)
        
        self.assertEqual(specials["special-movie-1"]["title"], "Special Movie 1")
        self.assertEqual(specials["special-movie-1"]["releaseAt"], "2026-07-20")
        self.assertEqual(specials["special-movie-1"]["genres"], ["Action"])
        
        self.assertEqual(specials["special-movie-3"]["title"], "Special Movie 3")
        self.assertEqual(specials["special-movie-3"]["releaseAt"], "2026-07-22")
        self.assertEqual(specials["special-movie-3"]["genres"], ["Sci-Fi", "Drama"])

    @patch("pathe_checker.fetch_html")
    @patch("pathe_checker.send_notification")
    @patch("os.path.exists")
    @patch("builtins.open", new_callable=mock_open)
    @patch("os.makedirs")
    def test_check_for_specials_dry_run(self, mock_makedirs, mock_file, mock_exists, mock_notify, mock_fetch):
        # Setup mock behavior
        mock_fetch.return_value = MOCK_HTML
        mock_exists.return_value = False  # cache does not exist
        
        # Define arguments Namespace
        args = MagicMock()
        args.url = "https://www.pathe.nl/en/films"
        args.data_dir = "/tmp/mock_data"
        args.dry_run = True
        args.clear_cache = False
        args.ntfy_topic = None
        
        # Execute check
        pathe_checker.check_for_specials(args)
        
        # Dry run should NOT write the cache file
        cache_calls = [call for call in mock_file.call_args_list if "specials_cache.json" in call[0][0]]
        self.assertEqual(len(cache_calls), 0)
        
        # Should not send notification
        mock_notify.assert_not_called()

    @patch("pathe_checker.fetch_html")
    @patch("pathe_checker.send_notification")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_check_for_specials_first_run(self, mock_makedirs, mock_exists, mock_notify, mock_fetch):
        mock_fetch.return_value = MOCK_HTML
        mock_exists.return_value = False  # cache does not exist
        
        args = MagicMock()
        args.url = "https://www.pathe.nl/en/films"
        args.data_dir = "/tmp/mock_data"
        args.dry_run = False
        args.clear_cache = False
        args.ntfy_topic = None
        
        # Use patch on open to catch the file write
        with patch("builtins.open", mock_open()) as mock_file:
            pathe_checker.check_for_specials(args)
            
            # Should create directory
            mock_makedirs.assert_called_with("/tmp/mock_data", exist_ok=True)
            
            # Should open specials_cache.json for writing
            cache_calls = [call for call in mock_file.call_args_list if "specials_cache.json" in call[0][0]]
            self.assertEqual(len(cache_calls), 1)
            self.assertEqual(cache_calls[0][0][1], "w")
            
            # Since cache did not exist previously, NO notification should be sent (first run initialization)
            mock_notify.assert_not_called()

    @patch("pathe_checker.fetch_html")
    @patch("pathe_checker.send_notification")
    @patch("os.path.exists")
    @patch("os.makedirs")
    def test_check_for_specials_new_movies_alert(self, mock_makedirs, mock_exists, mock_notify, mock_fetch):
        mock_fetch.return_value = MOCK_HTML
        mock_exists.return_value = True  # cache exists
        
        # Simulated cached content (only holds special-movie-1)
        cached_data = {
            "special-movie-1": {
                "title": "Special Movie 1",
                "slug": "special-movie-1",
                "releaseAt": "2026-07-20",
                "genres": ["Action"]
            }
        }
        
        args = MagicMock()
        args.url = "https://www.pathe.nl/en/films"
        args.data_dir = "/tmp/mock_data"
        args.dry_run = False
        args.clear_cache = False
        args.ntfy_topic = "test-topic"
        
        # Setup open mock to return the cached content for reading and accept writing
        mock_file_handler = mock_open(read_data=json.dumps(cached_data))
        with patch("builtins.open", mock_file_handler) as mock_file:
            pathe_checker.check_for_specials(args)
            
            # Should open specials_cache.json for reading first
            mock_file.assert_any_call("/tmp/mock_data/specials_cache.json", "r", encoding="utf-8")
            # Should send notification for the new movie: "Special Movie 3"
            mock_notify.assert_called_once_with(
                "Special Movie 3", 
                "Release: 2026-07-22 | Sci-Fi, Drama", 
                "/tmp/mock_data/pathe_checker.log", 
                "/tmp/mock_data",
                ntfy_topic="test-topic"
            )
            # Should update cache file
            mock_file.assert_any_call("/tmp/mock_data/specials_cache.json", "w", encoding="utf-8")

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_send_notification_applescript(self, mock_subrun, mock_urlopen):
        # When ntfy_topic is NOT provided
        pathe_checker.send_notification("Title", "Subtitle", ntfy_topic=None)
        mock_subrun.assert_called_once()
        mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    @patch("subprocess.run")
    def test_send_notification_ntfy(self, mock_subrun, mock_urlopen):
        # Mock response from urlopen
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response

        pathe_checker.send_notification("Title", "Subtitle", ntfy_topic="my-test-topic")
        mock_subrun.assert_not_called()
        mock_urlopen.assert_called_once()
        
        # Verify the request passed to urlopen
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://ntfy.sh/my-test-topic")
        self.assertEqual(req.data, b"Subtitle")
        self.assertEqual(req.get_header("Title"), "New Pathé Special: Title")
        self.assertEqual(req.get_header("Priority"), "high")
        self.assertEqual(req.get_header("Tags"), "movie_camera,popcorn")

if __name__ == "__main__":
    unittest.main()
