import os
import discord
import youtube_dl
import aiohttp
import asyncio
import logging

from .common import *

ytdl_format_options = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': 'audio_cache/%(id)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto'
}

logger = logging.getLogger('Player')

class Song:
    def __init__(self, url, title, downloaded=False):
        if not url.startswith('https'):
            self.id = url
            self.url = 'https://www.youtube.com/watch?v=' + url
        else:
            self.id = url.split('?v=')[1]
            self.url = url

        self.title = url
        
        if title is not None:
            self.title = title

        self.downloading = False
        self.downloaded = downloaded
        self.file_path = ''

    def _download(self, cls):

        download = True
        
        if self.id in os.listdir(cls.music_cache_dir):
            download = False

        if not self.downloaded:

            print(f'Downloading... {self.url}')

            with youtube_dl.YoutubeDL(ytdl_format_options) as ydl:
                self.downloading = True
                try:
                    info = ydl.extract_info(self.url, download=download)
                except youtube_dl.utils.DownloadError:
                    return {'error': True}
                self.title = info.get('title')
                self.id = info.get('id')
            
            self.downloaded = True
            self.downloading = False

            return {'error': False}

class MusicPlayer:
    def __init__(self):
        self.music_queue = []

    async def _youtube_search(self, query, **kwargs):
        url = 'https://www.googleapis.com/youtube/v3/search'
        params = {
            'part': 'snippet',
            'maxResults': 10,
            'q': query,
            'type': 'video',
            'key': self.youtube_apikey,
            **kwargs
        }

        result = []

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as r:
                if r.status == 200:
                    js = await r.json()
                    for r in js['items']:
                        result.append({
                            'id': r['id']['videoId'],
                            'title': r['snippet']['title']
                        })
                else:
                    return {'error': True, 'message': 'Network error. Please try again later'}

        return {'error': False, 'result': result}

    async def _process_query(self, *args, **kwargs):
        query = ' '.join(args)
        if query.startswith('youtube') or query.startswith('yt'):
            try:
                query = query.split(' ')[1]
            except IndexError:
                return

        if 'title' in kwargs:
            title = kwargs['title']
        else:
            title = None
        
        if query.startswith('https://www.youtube.com'):
            s = Song(query, title)
            r = await self._add_to_queue(s)
            if r['error']:
                await self.voice_text_channel.send('```fix\This video is not available :(```')
                return
        
        else:
            r = await self._youtube_search(query, maxResult=10)
            if not r['error']:
                i = 0
                while True:
                    s = r['result'][i]
                    song = Song(s['id'], s['title'])
                    ar = await self._add_to_queue(song)
                    if not ar['error']:
                        break
                    i += 1

    async def _add_to_queue(self, song_obj):
        self.music_queue.append(song_obj)
        
        await self.voice_text_channel.send('Adding %s...' % song_obj.url)

        for song in self.music_queue:
            if not song.downloaded and not song.downloading:
                logger.info('Downloading %s' % song.id)
                r = song._download(self)
                if r['error']:
                    return r
            else:
                logger.info('Skip downloading %s' % song.id)

        await self.voice_text_channel.send('```css\nAdded %s```' % song.title)

        await self._process_queue()

        return {'error': False}

    async def _process_queue(self):
        if len(self.music_queue) == 0:
            self.current_song = None
            return

        if not self.voice_client:
            return

        if self.voice_client.is_playing():
            return
        
        self.current_song = self.music_queue.pop(0)
        self.current_song.file_path = os.path.join(self.music_cache_dir, self.current_song.id)
        
        source = discord.FFmpegPCMAudio(self.current_song.file_path, executable='ffmpeg')

        await self.voice_text_channel.send('```fix\nNow playing: %s```' % self.current_song.title)

        try:
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._process_queue(), self.loop))
        except discord.errors.ClientException:
            self.voice_client.connect()
            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(self._process_queue(), self.loop))
