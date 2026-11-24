#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据网易云音乐专辑 / 歌单 / 单曲, 下载对应的无损 FLAC 歌曲到本地.

用法:
    python main.py "https://music.163.com/#/album?id=198202188"
    python main.py "https://music.163.com/#/playlist?id=145258012" --mp3
    python main.py "https://music.163.com/song?id=2162756781" --dry-run
    python main.py 198202188 --cookie "MUSIC_U=xxxxxxxx"

说明:
    网易云对无损(FLAC)资源要求登录且开通 VIP。未提供 cookie 时, 接口只会返回
    最高 320kbps 的 MP3, 此时默认(不加 --mp3)不会保存文件, 并会提示如何提供 cookie。
"""
import argparse
import collections
import json
import logging
import os
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import requests
import tqdm

API = "https://music.163.com"
KIND_LABEL = {"album": "专辑", "playlist": "歌单", "song": "单曲"}
DOWNLOAD_DIR = os.path.join(os.getcwd(), "songs_dir")
COOKIE_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "cookie.txt")
LOG_LEVEL = logging.INFO
LOG_FILE = "download.log"
LOG_FORMAT = "%(asctime)s %(filename)s:%(lineno)d [%(levelname)s] %(message)s"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Referer": "https://music.163.com/",
    "Accept": "*/*",
}
TIMEOUT = (10, 60)
CHUNK_SIZE = 64 * 1024
RETRY = 3
MAX_FILENAME_LEN = 150


def configure_windows_console():
    """Windows 控制台默认代码页无法编码中文, 切换为 UTF-8."""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def get_args():
    parser = argparse.ArgumentParser(
        usage="python main.py 专辑/歌单/单曲地址 [-m] [--cookie COOKIE]",
        description="根据网易云音乐专辑、歌单或单曲, 下载对应的无损 FLAC 歌曲到本地."
    )
    parser.add_argument("target", type=str, help="网易云音乐专辑 / 歌单 / 单曲 url, 也可以只给数字 id")
    parser.add_argument("-m", "--mp3", action="store_true", dest="mp3_option",
                        help="允许保存 MP3 (未提供 VIP cookie 时只能拿到 320kbps MP3)")
    parser.add_argument("--cookie", type=str, default=None,
                        help="登录后的 cookie, 例如 \"MUSIC_U=xxxx\"; 也可写入 cookie.txt 或设置环境变量 NETEASE_COOKIE")
    parser.add_argument("--level", type=str, default="lossless",
                        choices=["standard", "higher", "exhigh", "lossless", "hires"],
                        help="请求的音质等级, 默认 lossless(无损)")
    parser.add_argument("-o", "--outdir", type=str, default=DOWNLOAD_DIR, help="保存目录")
    parser.add_argument("-w", "--workers", type=int, default=5, help="并发线程数, 默认 5")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="只列出歌曲与可用音质, 不下载")
    return parser.parse_args()


def set_logger():
    logger = logging.getLogger()
    logger.setLevel(LOG_LEVEL)
    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if LOG_FILE:
        fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
        fh.setLevel(LOG_LEVEL)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


def validate_file_name(songname):
    """规范化文件名: NFKC 变体合并 + 去掉 Windows 保留字符."""
    songname = unicodedata.normalize("NFKC", songname or "")
    songname = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", songname)
    songname = re.sub(r"\s+", " ", songname).strip(" .")
    if len(songname) > MAX_FILENAME_LEN:
        songname = songname[:MAX_FILENAME_LEN].rstrip(" .")
    return songname or "unknown"


def parse_target(text):
    """识别链接类型和 id, 支持 #/album?id=1 / album?id=1 / 纯数字."""
    text = text.strip()
    m = re.search(r"music\.163\.com/(?:#/)?(album|playlist|song)\?id=(\d+)", text)
    if m:
        return m.group(1), m.group(2)
    if text.isdigit():
        return None, text
    raise ValueError("无法识别链接: %s (需要形如 https://music.163.com/#/album?id=198202188)" % text)


def build_session(cookie=None):
    session = requests.Session()
    session.headers.update(HEADERS)
    if cookie:
        session.headers["Cookie"] = cookie
    return session


def read_cookie(arg_cookie=None):
    if arg_cookie:
        return arg_cookie.strip()
    env = os.environ.get("NETEASE_COOKIE", "").strip()
    if env:
        return env
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return None


def normalize_song(raw):
    artists = raw.get("ar") or raw.get("artists") or []
    album = raw.get("al") or raw.get("album") or {}
    return {
        "id": raw["id"],
        "name": raw.get("name") or "",
        "artists": [a["name"] for a in artists if a.get("name")],
        "album": album.get("name") or "",
        "duration": raw.get("dt") or raw.get("duration") or 0,
        "fee": raw.get("fee"),
        "no": raw.get("no"),
    }


def chunked(seq, size=200):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def fetch_song_detail(session, song_ids):
    """批量取歌曲详情, 保持传入顺序."""
    if not song_ids:
        return []
    order = {sid: i for i, sid in enumerate(song_ids)}
    found = {}
    for chunk in chunked(list(song_ids)):
        try:
            r = session.get("%s/api/song/detail" % API,
                            params={"ids": json.dumps(chunk)}, timeout=TIMEOUT)
            songs = r.json().get("songs") or []
        except Exception as err:
            logger.warning("获取歌曲详情失败 (%s): %s", chunk[:3], err)
            continue
        for raw in songs:
            song = normalize_song(raw)
            found[song["id"]] = song
    return [found[sid] for sid in sorted(found, key=lambda x: order[x])]


def fetch_album(session, album_id):
    r = session.get("%s/api/v1/album/%s" % (API, album_id), timeout=TIMEOUT)
    payload = r.json()
    album = payload.get("album") or {}
    if payload.get("code") != 200 or not album:
        raise RuntimeError("专辑 %s 获取失败: %s" % (album_id, payload.get("message") or payload.get("code")))

    songs = [normalize_song(s) for s in payload.get("songs") or []]
    expected = album.get("size") or len(songs)
    if len(songs) < expected:
        # 大专辑可能只返回部分歌曲, 用 album.songs 里的 id 补齐
        have = {s["id"] for s in songs}
        missing = [sid for sid in album.get("songs") or [] if isinstance(sid, int) and sid not in have]
        songs.extend(fetch_song_detail(session, missing))
    return {
        "kind": "album",
        "id": album.get("id") or album_id,
        "name": album.get("name") or "album_%s" % album_id,
        "artist": "、".join(a.get("name", "") for a in album.get("artists") or []) or "",
        "cover": album.get("picUrl") or "",
        "songs": songs,
    }


def fetch_playlist(session, playlist_id):
    r = session.get("%s/api/v6/playlist/detail" % API,
                    params={"id": playlist_id, "n": 1000, "s": 0}, timeout=TIMEOUT)
    playlist = r.json().get("playlist") or {}
    if not playlist:
        raise RuntimeError("歌单 %s 获取失败" % playlist_id)

    track_ids = [t["id"] for t in playlist.get("trackIds") or [] if t.get("id")]
    songs = [normalize_song(s) for s in playlist.get("tracks") or []]
    have = {s["id"] for s in songs}
    missing = [sid for sid in track_ids if sid not in have]
    if missing:
        songs.extend(fetch_song_detail(session, missing))
    return {
        "kind": "playlist",
        "id": playlist.get("id") or playlist_id,
        "name": playlist.get("name") or "playlist_%s" % playlist_id,
        "artist": (playlist.get("creator") or {}).get("nickname") or "",
        "cover": playlist.get("coverImgUrl") or "",
        "songs": songs,
    }


def fetch_song(session, song_id):
    songs = fetch_song_detail(session, [int(song_id)])
    if not songs:
        raise RuntimeError("歌曲 %s 获取失败" % song_id)
    song = songs[0]
    return {
        "kind": "song",
        "id": song["id"],
        "name": song["name"],
        "album": song["album"],
        "artist": "、".join(song["artists"]),
        "cover": "",
        "songs": songs,
    }


def fetch_song_list(session, target, _id=None):
    """抓取专辑 / 歌单 / 单曲的歌曲列表."""
    kind, target_id = parse_target(target) if _id is None else (target, _id)
    if kind == "playlist":
        return fetch_playlist(session, target_id)
    if kind == "song":
        return fetch_song(session, target_id)
    if kind == "album":
        return fetch_album(session, target_id)
    # 纯数字: 先当专辑, 再当歌单
    try:
        return fetch_album(session, target_id)
    except Exception:
        return fetch_playlist(session, target_id)


def get_song_url(song_id, session, level="lossless"):
    """查询歌曲下载地址, 返回接口实际给出的音质信息."""
    last_err = None
    for attempt in range(RETRY):
        try:
            r = session.get("%s/api/song/enhance/player/url/v1" % API,
                            params={"ids": "[%s]" % song_id, "level": level, "encodeType": "flac"},
                            timeout=TIMEOUT)
            data = (r.json().get("data") or [{}])[0]
            return {
                "url": data.get("url"),
                "type": (data.get("type") or "").lower(),
                "br": data.get("br") or 0,
                "size": data.get("size") or 0,
                "level": data.get("level") or "",
                "code": data.get("code"),
                "fee": data.get("fee"),
            }
        except Exception as err:
            last_err = err
            time.sleep(1 + attempt)
    logger.error("查询歌曲 %s 下载地址失败: %s", song_id, last_err)
    return {"url": None, "type": "", "br": 0, "size": 0, "level": "", "code": None, "fee": None}


def pick_extension(url_info):
    if url_info.get("type") in ("flac", "mp3"):
        return "." + url_info["type"]
    path = (url_info.get("url") or "").split("?")[0]
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in (".flac", ".mp3") else ".bin"


def build_filename(song, ext, index=None):
    artist = "、".join(song["artists"]) or "未知歌手"
    base = "%s - %s" % (song["name"], artist)
    if index is not None:
        base = "%02d. %s" % (index, base)
    return validate_file_name(base) + ext


def download_song(song, url_info, session, download_folder, display, counter, index=None):
    ext = pick_extension(url_info)
    filename = build_filename(song, ext, index)
    filepath = os.path.join(download_folder, filename)

    if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
        logger.info("已存在, 跳过: %s", filename)
        counter["exists"] += 1
        if display:
            display.update()
        return filepath

    tmp_path = filepath + ".part"
    last_err = None
    for attempt in range(RETRY):
        try:
            with session.get(url_info["url"], timeout=TIMEOUT, stream=True) as r:
                r.raise_for_status()
                written = 0
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
            if written == 0:
                raise IOError("空文件")
            expected = url_info.get("size") or 0
            if expected and written < expected * 0.98:
                raise IOError("文件不完整: %s/%s 字节" % (written, expected))
            os.replace(tmp_path, filepath)
            size_mb = round(written / (1024 ** 2), 1)
            logger.info("下载完成: %s (%s MB, %s)", filename, size_mb, url_info.get("level") or ext)
            counter["flac" if ext == ".flac" else "mp3"] += 1
            if display:
                display.update()
            return filepath
        except Exception as err:
            last_err = err
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            time.sleep(1 + attempt)

    logger.error("下载失败: %s (%s)", filename, last_err)
    counter["failed"] += 1
    if display:
        display.update()
    return None


def check_flac_hint(cookie):
    hint = ("接口只返回了 MP3 (最高 320kbps)。网易云的无损 FLAC 需要登录且有 VIP 权限:\n"
            "  1) 用浏览器登录 https://music.163.com\n"
            "  2) F12 -> Application/存储 -> Cookies -> 复制 MUSIC_U 的值\n"
            "  3) 重新运行: python main.py \"<链接>\" --cookie \"MUSIC_U=复制的值\"\n"
            "  (也可以把 cookie 存到脚本目录下的 cookie.txt, 或设置环境变量 NETEASE_COOKIE)\n"
            "  想先下载 320kbps MP3 的话, 加 -m / --mp3 参数。")
    if cookie:
        hint = "已提供 cookie, 但仍未拿到 FLAC —— 请确认该账号已开通 VIP 且 cookie 未过期。\n" + hint
    return hint


def main():
    start = time.time()
    configure_windows_console()
    args = get_args()

    logger.info("=" * 70)
    cookie = read_cookie(args.cookie)
    session = build_session(cookie)
    if cookie:
        logger.info("已使用 cookie 登录状态 (长度 %d)", len(cookie))
    else:
        logger.info("未提供 cookie, 将以游客身份请求 (无法获取无损 FLAC)")

    target = fetch_song_list(session, args.target)
    songs = target["songs"]
    logger.info("%s: %s%s", KIND_LABEL.get(target["kind"], "歌单"),
                target["name"], " - " + target["artist"] if target["artist"] else "")
    logger.info("共 %d 首歌曲:", len(songs))
    for i, song in enumerate(songs, 1):
        logger.info("  %02d. %s - %s", i, song["name"], "、".join(song["artists"]))
    if not songs:
        logger.error("没有解析到任何歌曲, 退出。")
        sys.exit(1)

    folder_name = target.get("album") or target["name"]
    download_folder = os.path.join(args.outdir, validate_file_name(folder_name))
    if not args.dry_run and not os.path.exists(download_folder):
        os.makedirs(download_folder, exist_ok=True)
    logger.info("保存目录: %s", download_folder)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        url_infos = list(executor.map(partial(get_song_url, session=session, level=args.level), [s["id"] for s in songs]))

    pairs = list(zip(songs, url_infos))
    available = [(i, s, u) for i, (s, u) in enumerate(pairs, 1) if u["url"]]
    missing = [(i, s) for i, (s, u) in enumerate(pairs, 1) if not u["url"]]
    flac_items = [(i, s, u) for i, s, u in available if u.get("type") == "flac"]
    mp3_items = [(i, s, u) for i, s, u in available if u.get("type") != "flac"]

    for i, s in missing:
        logger.warning("%02d. %s - %s: 无版权 / 已下架, 跳过", i, s["name"], "、".join(s["artists"]))

    if args.dry_run:
        for i, s, u in available:
            logger.info("%02d. %s | 实际音质: %s / %skbps / %s",
                        i, s["name"], u.get("level") or u.get("type"), (u.get("br") or 0) // 1000, u.get("type"))
        if mp3_items and not args.mp3_option:
            logger.info("其中 %d 首没有 FLAC, 默认不会保存 (加 -m 可一起下载)。", len(mp3_items))
        logger.info("--dry-run 模式, 未下载任何文件。")
        return

    skipped_mp3 = 0
    if flac_items:
        if args.mp3_option:
            logger.info("检测到 %d 首无损资源, 连同 MP3 一起下载。", len(flac_items))
            to_download = available
        else:
            logger.info("检测到 %d 首无损资源, 开始下载 FLAC。", len(flac_items))
            if mp3_items:
                logger.warning("%d 首没有 FLAC 资源, 已跳过 (加 -m 可一起下载)。", len(mp3_items))
            skipped_mp3 = len(mp3_items)
            to_download = flac_items
    elif args.mp3_option:
        logger.warning("未获取到 FLAC, 按 --mp3 参数下载 MP3。\n%s", check_flac_hint(cookie))
        to_download = available
    else:
        logger.error("未获取到无损 FLAC 资源。\n%s", check_flac_hint(cookie))
        to_download = []

    counter = collections.Counter()
    display = tqdm.tqdm(total=len(to_download)) if to_download else None
    download = partial(download_song, session=session, download_folder=download_folder,
                       display=display, counter=counter)
    if to_download:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            list(executor.map(lambda item: download(item[1], item[2], index=item[0]), to_download))
    if display:
        display.close()

    end = time.time()
    logger.info("共耗时 %.1f s", end - start)
    logger.info("共 %d 首歌曲: FLAC %d 首, MP3 %d 首, 已存在跳过 %d 首, 下载失败 %d 首, 无 FLAC 跳过 %d 首, 无资源 %d 首",
                len(songs), counter["flac"], counter["mp3"], counter["exists"],
                counter["failed"], skipped_mp3, len(missing))
    logger.info("文件位于: %s", download_folder)


logger = set_logger()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("已中断")
        sys.exit(130)
