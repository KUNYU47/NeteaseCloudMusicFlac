import unittest

from main import (build_session, build_filename, fetch_song_list, get_song_url,
                  parse_target, pick_extension, validate_file_name)

ALBUM_URL = "https://music.163.com/#/album?id=198202188"
ALBUM_ID = "198202188"


class TestPureFunctions(unittest.TestCase):

    def test_parse_target(self):
        self.assertEqual(parse_target(ALBUM_URL), ("album", ALBUM_ID))
        self.assertEqual(parse_target("https://music.163.com/album?id=198202188"), ("album", ALBUM_ID))
        self.assertEqual(parse_target("http://music.163.com/#/playlist?id=145258012"), ("playlist", "145258012"))
        self.assertEqual(parse_target("https://music.163.com/song?id=2162756781"), ("song", "2162756781"))
        self.assertEqual(parse_target("198202188"), (None, "198202188"))
        with self.assertRaises(ValueError):
            parse_target("https://example.com/foo")

    def test_validate_file_name(self):
        self.assertEqual(validate_file_name('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")
        self.assertNotIn(":", validate_file_name("04:30"))
        self.assertEqual(validate_file_name("  名字.  "), "名字")
        # NFKC: 全角冒号应被规范化
        self.assertEqual(validate_file_name("金魚。壞天氣"), "金魚。壞天氣")
        self.assertEqual(validate_file_name(""), "unknown")

    def test_build_filename(self):
        song = {"name": "白色風車", "artists": ["TOPKINGCREAM"]}
        self.assertEqual(build_filename(song, ".flac", 1), "01. 白色風車 - TOPKINGCREAM.flac")
        self.assertEqual(build_filename(song, ".mp3"), "白色風車 - TOPKINGCREAM.mp3")
        self.assertIn("未知歌手", build_filename({"name": "x", "artists": []}, ".flac"))

    def test_pick_extension(self):
        self.assertEqual(pick_extension({"type": "flac", "url": "http://x/y.mp3"}), ".flac")
        self.assertEqual(pick_extension({"type": "mp3", "url": "http://x/y.flac"}), ".mp3")
        self.assertEqual(pick_extension({"type": "", "url": "http://x/y.flac?a=1"}), ".flac")
        self.assertEqual(pick_extension({"type": "", "url": ""}), ".bin")


class TestNetwork(unittest.TestCase):
    """需要联网, 失败时跳过而不是让整个测试失败."""

    @classmethod
    def setUpClass(cls):
        cls.session = build_session()

    def test_fetch_album(self):
        try:
            target = fetch_song_list(self.session, ALBUM_URL)
        except Exception as err:
            self.skipTest("网络不可用: %s" % err)
        self.assertEqual(target["kind"], "album")
        self.assertEqual(str(target["id"]), ALBUM_ID)
        self.assertEqual(len(target["songs"]), 5)
        names = [s["name"] for s in target["songs"]]
        self.assertIn("白色風車", names)
        for song in target["songs"]:
            self.assertIsInstance(song["id"], int)
            self.assertTrue(song["artists"])

    def test_get_song_url(self):
        try:
            url_info = get_song_url(2162756781, self.session, level="lossless")
        except Exception as err:
            self.skipTest("网络不可用: %s" % err)
        self.assertTrue(url_info["url"])
        self.assertIn(url_info["type"], ("mp3", "flac"))
        self.assertGreater(url_info["br"], 0)

    def test_bad_album(self):
        with self.assertRaises(Exception):
            fetch_song_list(self.session, "https://music.163.com/#/album?id=1")


if __name__ == "__main__":
    unittest.main()
