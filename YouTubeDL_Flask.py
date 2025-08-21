#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import threading
import time
import base64
from datetime import datetime

# Render用: 環境変数からcookies.txtを復元
cookies_b64 = os.getenv("COOKIES_B64")
if cookies_b64:
    try:
        with open("cookies.txt", "wb") as f:
            f.write(base64.b64decode(cookies_b64))
        print("✅ Cookies restored from environment variable")
    except Exception as e:
        print(f"❌ Failed to restore cookies: {e}")
else:
    print("ℹ️ No COOKIES_B64 environment variable found")

app = Flask(__name__)

class YouTubeDLWeb:
    def __init__(self):
        self.download_status = {}
        self.current_download = None
    
    def get_download_options(self, output_dir, quality, format_type, url):
        quality_map = {"最高画質": "best", "720p": "best[height<=720]", "480p": "best[height<=480]"}
        format_map = {"MP4": quality_map.get(quality, "best"), "MP3": "bestaudio/best"}
        
        is_playlist = 'playlist' in url or 'list=' in url
        template = '%(playlist_index)03d - %(title)s.%(ext)s' if is_playlist else '%(title)s.%(ext)s'
        
        opts = {
            'outtmpl': f'{output_dir}/{template}',
            'format': format_map.get(format_type, "best"),
            'progress_hooks': [self.progress_hook],
            # Cookies設定（最優先）
            'cookiefile': './cookies.txt' if os.path.exists('./cookies.txt') else None,
            # Bot検出回避設定
            'extractor_args': {
                'youtube': {
                    'skip': ['hls', 'dash'],
                    'player_skip': ['js'],
                }
            },
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'referer': 'https://www.youtube.com/',
            'sleep_interval': 1,
            'max_sleep_interval': 5,
            'ignoreerrors': False,
            'no_warnings': False
        }
        
        if format_type == "MP3":
            opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}]
        
        return opts
    
    def progress_hook(self, d):
        if self.current_download:
            if d['status'] == 'downloading':
                current = d.get('info_dict', {}).get('playlist_index', 1)
                self.download_status[self.current_download] = {
                    'status': 'downloading',
                    'current': current,
                    'total': getattr(self, 'total_files', 1),
                    'message': f"ダウンロード中: {current}/{getattr(self, 'total_files', 1)} ファイル"
                }
            elif d['status'] == 'finished':
                self.completed_files = getattr(self, 'completed_files', 0) + 1
                if hasattr(self, 'total_files') and self.total_files > 0:
                    percent = self.completed_files / self.total_files
                    self.download_status[self.current_download] = {
                        'status': 'progress',
                        'percent': percent * 100,
                        'completed': self.completed_files,
                        'total': self.total_files,
                        'message': f"進行状況: {self.completed_files}/{self.total_files} ファイル ({percent*100:.1f}%)"
                    }
    
    def download_video(self, url, quality, format_type):
        download_id = str(int(time.time()))
        self.current_download = download_id
        self.completed_files = 0
        
        try:
            # Create temp directory
            temp_dir = f'./temp_{download_id}'
            os.makedirs(temp_dir, exist_ok=True)
            
            # Get total files count
            try:
                info_opts = {
                    'quiet': True,
                    'cookiefile': './cookies.txt' if os.path.exists('./cookies.txt') else None,
                    'extractor_args': {
                        'youtube': {
                            'skip': ['hls', 'dash'],
                            'player_skip': ['js'],
                        }
                    },
                    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'referer': 'https://www.youtube.com/',
                }
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    self.total_files = len(list(info['entries'])) if 'entries' in info else 1
                    video_title = info.get('title', 'video')
            except:
                self.total_files = 1
                video_title = 'video'
            
            # Get download options
            ydl_opts = self.get_download_options(temp_dir, quality, format_type, url)
            
            # Download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Find downloaded file
            files = os.listdir(temp_dir)
            if files:
                filename = files[0]
                self.download_status[download_id] = {
                    'status': 'completed',
                    'message': f"完了: {filename}",
                    'filename': filename,
                    'temp_dir': temp_dir
                }
            else:
                raise Exception('ファイルが見つかりません')
            
        except Exception as e:
            self.download_status[download_id] = {
                'status': 'error',
                'message': f"エラー: {str(e)}"
            }
        
        return download_id

downloader = YouTubeDLWeb()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    data = request.json
    url = data.get('url', '').strip()
    quality = data.get('quality', '最高画質')
    format_type = data.get('format', 'MP4')
    
    if not url:
        return jsonify({'error': 'URLを入力してください'}), 400
    
    # Start download in background thread
    def start_download():
        downloader.download_video(url, quality, format_type)
    
    thread = threading.Thread(target=start_download, daemon=True)
    thread.start()
    
    return jsonify({'status': 'started', 'message': 'ダウンロードを開始しました'})

@app.route('/download_file/<filename>')
def download_file(filename):
    # Find the temp directory containing this file
    for download_id, status in downloader.download_status.items():
        if status.get('filename') == filename and 'temp_dir' in status:
            file_path = os.path.join(status['temp_dir'], filename)
            if os.path.exists(file_path):
                return send_file(file_path, as_attachment=True, download_name=filename)
    return 'File not found', 404

@app.route('/status')
def status():
    if downloader.current_download and downloader.current_download in downloader.download_status:
        return jsonify(downloader.download_status[downloader.current_download])
    return jsonify({'status': 'ready', 'message': '準備完了'})

if __name__ == '__main__':
    # Create templates directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    app.run(debug=True, host='0.0.0.0', port=8080)