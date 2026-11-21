"""Synthetic clips and frame readers for the clip tests (package V9b-5a). Every clip is made here by the host's ffmpeg, from generated frames: a moving
gradient with the frame number written as eight black and white blocks, so a test can read which frame of the clip a frame of the output shows. Nothing real is
used. The tests that use these are skipped without ffmpeg."""
from __future__ import annotations

import subprocess

import renderer_kit as K

BLOCK = 32          # a bit's block is this many pixels wide, in the top row of the clip
BITS = 8


def ffmpeg(*args, timeout=300):
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True, timeout=timeout)


def counter_source(w: int, h: int, frames: int, fps: int = 30) -> str:
    """The lavfi source text of the counter clip: bit k of the frame number N is white or black in the block at x in [32k, 32k+32), y < 32; the rest is a gradient
    that moves with N."""
    bit = "255*mod(floor(N/pow(2,floor(X/%d))),2)" % BLOCK
    expr = "if(lt(Y,%d),if(lt(X,%d),%s,mod(X+4*N,256)),mod(X+4*N,256))" % (BLOCK, BLOCK * BITS, bit)
    return "nullsrc=s=%dx%d:r=%d:d=%f,geq=lum='%s':cb=128:cr=128" % (w, h, fps, frames / float(fps), expr)


def counter_clip(path, w: int, h: int, frames: int, fps: int = 30, codec_args=("-c:v", "libx264"), extra=()) -> str:
    """An MP4 (or what `path`'s name and `codec_args` say) of the counter clip, yuv420p."""
    ffmpeg("-f", "lavfi", "-i", counter_source(w, h, frames, fps), "-pix_fmt", "yuv420p", *codec_args, *extra, str(path))
    return str(path)


def flat_clip(path, w: int, h: int, seconds: float, colour: str = "0x2060C0", fps: int = 30, codec_args=("-c:v", "libx264"), extra=(), bt709: bool = False) -> str:
    """A flat-colour clip. With `bt709` the colour is converted through the bt709 matrix and the clip is tagged so (otherwise the source's own, untagged, conversion)."""
    source = "color=c=%s:s=%dx%d:r=%d:d=%s" % (colour, w, h, fps, seconds)
    if bt709:
        ffmpeg("-f", "lavfi", "-i", source + ",format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
               "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", *codec_args, *extra, str(path))
    else:
        ffmpeg("-f", "lavfi", "-i", source, "-pix_fmt", "yuv420p", *codec_args, *extra, str(path))
    return str(path)


def rgb_at(video, frame: int, x: int, y: int) -> tuple:
    """The (r, g, b) of one pixel of one frame of a video."""
    raw = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", str(video), "-vf", "select=eq(n\\,%d),format=rgb24,crop=1:1:%d:%d" % (frame, x, y),
                          "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=120).stdout
    return tuple(raw[:3])


def frame_number(video, frame: int, x0: int = 0, y0: int = 0, scale: float = 1.0) -> int:
    """The frame number a frame of the output shows, read from the counter blocks of the clip drawn at (x0, y0) and scaled by `scale`. A clip frame is
    lossy, so a bit is white when its green channel is over 128."""
    value = 0
    for k in range(BITS):
        if rgb_at(video, frame, int(x0 + (BLOCK * k + BLOCK // 2) * scale), int(y0 + (BLOCK // 2) * scale))[1] > 128:
            value |= 1 << k
    return value


def frames_of(video) -> int:
    out = subprocess.run([K.FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video)],
                         capture_output=True, check=True, text=True, timeout=120).stdout
    return int(out.strip())
