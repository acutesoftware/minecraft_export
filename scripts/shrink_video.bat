ffmpeg -i flyover_2026-09-19.mp4 -vf "scale=600:352" -vcodec libx264 -crf 28 -acodec copy compressed_demo.mp4
