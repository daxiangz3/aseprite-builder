import sys
import os
import subprocess
import threading
import time
import datetime
import json
import tempfile
import io
import re
import webbrowser

import requests
import pygame
from flask import Flask, request, jsonify, render_template_string

# ---------- 配置 ----------
PORT = 5000
HOST = "0.0.0.0"

# ---------- 网易云 API ----------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}

def search_songs(keyword):
    """搜索歌曲，返回列表 [{id, name, artists, album, fee}]"""
    url = "https://music.163.com/api/search/get"
    params = {"s": keyword, "type": 1, "limit": 20}
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        if data["code"] != 200:
            return []
        songs = data.get("result", {}).get("songs", [])
        result = []
        for song in songs:
            result.append({
                "id": song["id"],
                "name": song["name"],
                "artists": ", ".join(a["name"] for a in song["artists"]),
                "album": song["album"]["name"],
                "fee": song.get("fee", 0),       # 1 表示 VIP
            })
        return result
    except Exception as e:
        print(f"搜索失败: {e}")
        return []

def get_song_url(song_id):
    """获取歌曲播放直链（优先 320k，失败降级 128k）"""
    for br in [320000, 128000]:
        url = f"https://music.163.com/api/song/enhance/player/url?id={song_id}&ids=[{song_id}]&br={br}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            data = resp.json()
            if data["code"] == 200 and data.get("data"):
                song_url = data["data"][0].get("url")
                if song_url:
                    return song_url
        except:
            continue
    return None

# ---------- 播放器线程 ----------
class MusicPlayer:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_song_info = {"name": "", "artist": ""}
        self.stop_event = threading.Event()
        self.play_thread = None
        self.queue = []
        pygame.mixer.init()

    def play_song(self, song_info):
        """外部调用，将歌曲加入播放队列并启动线程"""
        with self.lock:
            self.queue.append(song_info)
        if self.play_thread is None or not self.play_thread.is_alive():
            self.stop_event.clear()
            self.play_thread = threading.Thread(target=self._play_loop, daemon=True)
            self.play_thread.start()

    def _play_loop(self):
        while True:
            with self.lock:
                if not self.queue:
                    break
                song = self.queue.pop(0)
            self._download_and_play(song)
            if self.stop_event.is_set():
                with self.lock:
                    self.queue.clear()
                self.stop_event.clear()

    def _download_and_play(self, song):
        sid = song["id"]
        name = song["name"]
        artist = song["artist"]
        print(f"正在获取: {name} - {artist}")
        url = get_song_url(sid)
        if not url:
            print(f"获取播放链接失败: {name}")
            return

        # 下载到临时文件
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        try:
            resp = requests.get(url, headers=HEADERS, stream=True, timeout=30)
            for chunk in resp.iter_content(chunk_size=8192):
                if self.stop_event.is_set():
                    break
                tmp.write(chunk)
            tmp.close()
            if self.stop_event.is_set():
                os.unlink(tmp.name)
                return
            # 播放
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.play()
            self.current_song_info = {"name": name, "artist": artist}
            print(f"正在播放: {name}")
            while pygame.mixer.music.get_busy():
                if self.stop_event.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.2)
            pygame.mixer.music.unload()
        except Exception as e:
            print(f"播放异常: {e}")
        finally:
            try:
                os.unlink(tmp.name)
            except:
                pass

    def stop(self):
        """外部调用，停止播放并清空队列"""
        self.stop_event.set()
        pygame.mixer.music.stop()
        with self.lock:
            self.queue.clear()
        self.current_song_info = {"name": "", "artist": ""}

    def status(self):
        return {
            "playing": pygame.mixer.music.get_busy(),
            "name": self.current_song_info["name"],
            "artist": self.current_song_info["artist"],
        }

player = MusicPlayer()

# ---------- 系统控制 ----------
def execute_cmd(command):
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
