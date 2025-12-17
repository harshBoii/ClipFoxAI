import ffmpeg
import requests
from typing import Optional
import os
def download_video(api_url: str, filename: str) -> str:
    """Download video from API endpoint"""
    print(f"📥 Downloading from: {api_url}")
    
    # Call API to get real video URL
    api_response = requests.get(api_url, timeout=30)
    api_data = api_response.json()
    
    if not api_data.get('success') or not api_data.get('download', {}).get('url'):
        raise Exception("Invalid API response - no download URL")
    
    real_video_url = api_data['download']['url']
    
    # Download actual video
    response = requests.get(real_video_url, stream=True, timeout=300)
    response.raise_for_status()
    
    with open(filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    
    return filename

def get_video_info(filename: str) -> tuple[int, int, float]:
    """Get video dimensions and duration"""
    try:
        probe = ffmpeg.probe(filename)
        video_stream = next(
            (stream for stream in probe['streams'] if stream['codec_type'] == 'video'), 
            None
        )
        if not video_stream:
            raise Exception("No video stream found")
        
        width = int(video_stream['width'])
        height = int(video_stream['height'])
        duration = float(probe['format']['duration'])
        
        return width, height, duration
    except Exception as e:
        print(f"❌ Probe error: {e}")
        raise

def process_video(
    input_file: str, 
    output_file: str, 
    crop: Optional[tuple] = None, 
    resize: Optional[tuple] = None, 
    trim: Optional[tuple] = None
) -> None:
    """Process video with ffmpeg"""
    print("⚙️ Processing video...")
    
    # Build filter chain
    vf_filters = []
    if crop:
        vf_filters.append(f"crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]}")
    if resize:
        vf_filters.append(f"scale={resize[0]}:{resize[1]}")
    
    vf = ','.join(vf_filters) if vf_filters else None
    
    try:
        # Setup input with optional trim
        if trim:
            input_stream = ffmpeg.input(
                input_file, 
                ss=trim[0], 
                t=trim[1] - trim[0]
            )
        else:
            input_stream = ffmpeg.input(input_file)
        
        # Build output
        output_kwargs = {
            'vcodec': 'libx264',
            'preset': 'medium',
            'crf': 23,
            'acodec': 'aac',
            'audio_bitrate': '128k',
            'movflags': '+faststart'
        }
        
        if vf:
            output_kwargs['vf'] = vf
        
        stream = ffmpeg.output(input_stream, output_file, **output_kwargs)
        
        # Execute with overwrite
        ffmpeg.run(stream, overwrite_output=True, capture_stdout=True, capture_stderr=True)
        print("✅ Processing complete!")
        
    except ffmpeg.Error as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"❌ FFmpeg error: {error_msg}")
        raise Exception(f"Video processing failed: {error_msg}")

def cleanup_files(*files):
    """Clean up temporary files"""
    for file in files:
        try:
            if os.path.exists(file):
                os.remove(file)
                print(f"🗑️ Cleaned up: {file}")
        except Exception as e:
            print(f"⚠️ Cleanup error for {file}: {e}")
