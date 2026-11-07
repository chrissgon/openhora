#!/bin/sh
# The entry script of the transcriber image (providers/transcriber/Dockerfile). The provider starts the container
# with no network, a read-only root file system and these mounts:
#   /in/input         the audio or video file, read-only
#   /models/model.bin the whisper model, read-only (its sha256 was checked on the host before the start)
#   /out              the one folder this script writes: transcript.json, input_duration.txt, audio_duration.txt
#   /scratch, /tmp    memory-backed scratch (tmpfs), gone with the container
# Usage: openhora-transcribe <threads> <language> <timestamps: word|ml1|dtw> <dtw preset or -> <max audio seconds> <run seconds>
# <run seconds> bounds each of ffmpeg and whisper-cli with timeout(1) (exit 124): a stuck tool ends before the provider's own
# timeout removes the container.
# Exit codes: 0 done; 20 the input is longer than the limit; 21 the input's duration is unknown; 22 usage; anything
# else is the failing program's own code. Nothing of the audio's text is printed: whisper's output goes to /dev/null
# and its logs are off (-np), so only the errors of the tools reach the container's stderr.
set -eu
[ "$#" -eq 6 ] || { echo "usage: openhora-transcribe <threads> <language> <word|ml1|dtw> <dtw preset|-> <max audio seconds> <run seconds>" >&2; exit 22; }
threads=$1; language=$2; mode=$3; preset=$4; max_seconds=$5; run_seconds=$6

duration=$(timeout -k 5 "$run_seconds" ffprobe -v error -protocol_whitelist file,pipe -show_entries format=duration -of csv=p=0 /in/input 2>/dev/null | head -n 1 || true)
case "$duration" in
  ""|N/A) echo "the input's duration is unknown" >&2; exit 21 ;;
esac
printf '%s\n' "$duration" > /out/input_duration.txt
if awk -v d="$duration" -v m="$max_seconds" 'BEGIN { exit !(d + 0 > m + 0) }'; then
  echo "the input is longer than the limit of $max_seconds seconds" >&2
  exit 20
fi

# 16 kHz, mono, signed 16-bit PCM: the one input whisper-cli reads without help. -t is a second bound on what is read.
timeout -k 5 "$run_seconds" ffmpeg -nostdin -hide_banner -loglevel error -y -protocol_whitelist file,pipe -t "$max_seconds" -i /in/input \
  -vn -sn -dn -map 0:a:0 -ar 16000 -ac 1 -c:a pcm_s16le -f wav /scratch/audio.wav
timeout -k 5 "$run_seconds" ffprobe -v error -show_entries format=duration -of csv=p=0 /scratch/audio.wav | head -n 1 > /out/audio_duration.txt

# -np: no logs. -ng: CPU. -ojf: the JSON with every token and its times. -of: the output name without its extension.
set -- whisper-cli -m /models/model.bin -f /scratch/audio.wav -l "$language" -t "$threads" -np -ng -ojf -of /out/transcript
case "$mode" in
  word) ;;
  ml1)  set -- "$@" -ml 1 -sow ;;
  dtw)  set -- "$@" -nfa -dtw "$preset" ;;   # -nfa: whisper.cpp switches DTW off while flash attention is on
  *)    echo "unknown timestamps mode" >&2; exit 22 ;;
esac
timeout -k 5 "$run_seconds" "$@" > /dev/null
