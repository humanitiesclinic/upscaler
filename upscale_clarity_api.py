#!/usr/bin/env python
import sys
import os
import json
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import argparse
import time
import base64


class ClarityAIUpscaler:
    """Upscale images/videos using ClarityAI API with multiple modes."""
    
    SUPPORTED_IMAGE_FORMATS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif'}
    SUPPORTED_VIDEO_FORMATS = {'.mp4', '.webm', '.mov', '.avi'}
    API_ENDPOINT = "https://api-upscale.clarityai.co"
    
    MODES = {
        'crystal': {'desc': 'Crystal - High-precision upscaling for all images'},
        'crystal-video': {'desc': 'Crystal Video - High-precision video upscaling'},
        'clarity': {'desc': 'Clarity - Classic with fine-grained control'},
        'clarity-pro': {'desc': 'Clarity Pro - Next-gen for portraits & skin'}
    }
    
    def __init__(self, api_key: str, output_dir: str = "upscaled_output", github_pages_url: str = "https://humanitiesclinic.github.io/upscaler"):
        """Initialize upscaler with API key and output directory."""
        self.api_key = api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.github_pages_url = github_pages_url
    
    def is_image(self, file_path: Path) -> bool:
        """Check if file is a supported image format."""
        return file_path.suffix.lower() in self.SUPPORTED_IMAGE_FORMATS
    
    def is_video(self, file_path: Path) -> bool:
        """Check if file is a supported video format."""
        return file_path.suffix.lower() in self.SUPPORTED_VIDEO_FORMATS
    
    def collect_inputs(self, inputs: List[str], file_type: str = 'image') -> Tuple[List[Path], List[str]]:
        """Collect files, folders, and URLs. Returns (local_files, urls)."""
        files = []
        urls = []
        check_func = self.is_image if file_type == 'image' else self.is_video
        
        for input_str in inputs:
            # Check if it's a URL
            if input_str.startswith('http://') or input_str.startswith('https://'):
                urls.append(input_str)
            else:
                path = Path(input_str)
                
                if path.is_dir():
                    # Recursively find all files in directory
                    for item in path.rglob('*'):
                        if item.is_file() and check_func(item):
                            files.append(item)
                elif path.is_file():
                    # Check if it's a txt file with URLs
                    if input_str.lower().endswith('.txt'):
                        try:
                            with open(path, 'r') as f:
                                for line in f:
                                    line = line.strip()
                                    # Skip empty lines and comments
                                    if line and not line.startswith('#'):
                                        if line.startswith('http://') or line.startswith('https://'):
                                            urls.append(line)
                                        else:
                                            print(f"⚠ Skipping invalid URL in {path.name}: {line}")
                            print(f"  ✓ Loaded {len([u for u in urls])} URL(s) from {path.name}")
                        except Exception as e:
                            print(f"⚠ Failed to read {path.name}: {e}")
                    elif check_func(path):
                        files.append(path)
                    else:
                        print(f"⚠ Skipping unsupported file: {path}")
                else:
                    print(f"⚠ Not found: {input_str}")
        
        return sorted(files), urls
    
    def upload_image_to_url(self, image_path: Path) -> Optional[str]:
        """Build GitHub Pages URL for image in docs folder."""
        try:
            # Copy file to docs folder if not already there
            docs_path = Path('docs')
            docs_path.mkdir(exist_ok=True)
            dest_file = docs_path / image_path.name
            
            # Copy file to docs
            with open(image_path, 'rb') as src:
                with open(dest_file, 'wb') as dst:
                    dst.write(src.read())
            
            # Commit and push to GitHub
            import subprocess
            try:
                subprocess.run(['git', 'add', 'docs/'], check=True, capture_output=True)
                subprocess.run(['git', 'commit', '-m', f'Add {image_path.name} to docs for upscaling'], 
                             capture_output=True)
                subprocess.run(['git', 'push'], check=True, capture_output=True)
                print(f"  ✓ Pushed {image_path.name} to GitHub")
            except subprocess.CalledProcessError as git_err:
                # If commit/push fails, still proceed (file is in docs)
                print(f"  ⚠ Git push failed: {git_err}")
            
            # Return GitHub Pages URL
            url = f"{self.github_pages_url}/docs/{image_path.name}"
            return url
        except Exception as e:
            print(f"✗ Failed to upload to docs: {e}")
            return None
    
    def build_request_payload(self, mode: str, file_path: Optional[Path], settings: Dict, is_video: bool = False, direct_url: Optional[str] = None) -> Dict:
        """Build request payload based on mode."""
        file_key = 'video' if is_video else 'image'
        
        # Use direct URL if provided, otherwise upload local file
        if direct_url:
            file_url = direct_url
        else:
            file_url = self.upload_image_to_url(file_path)
        
        payload = {
            'mode': mode,
            file_key: file_url
        }
        
        if mode == 'crystal':
            payload.update({
                'scale_factor': settings.get('scale_factor', 2),
                'creativity': settings.get('creativity', 0),
                'output_format': settings.get('output_format', 'jpg')
            })
            if 'target_megapixels' in settings:
                payload['target_megapixels'] = settings['target_megapixels']
        
        elif mode == 'crystal-video':
            payload['scale_factor'] = settings.get('scale_factor', 2)
        
        elif mode == 'clarity':
            payload.update({
                'creativity': settings.get('creativity', 0),
                'resemblance': settings.get('resemblance', 0),
                'dynamic': settings.get('dynamic', 0),
                'fractality': settings.get('fractality', 0),
                'scale_factor': settings.get('scale_factor', 2),
                'style': settings.get('style', 'default')
            })
            if 'prompt' in settings:
                payload['prompt'] = settings['prompt']
        
        elif mode == 'clarity-pro':
            payload.update({
                'creativity': settings.get('creativity', 0),
                'scale_factor': settings.get('scale_factor', 2),
                'output_format': settings.get('output_format', 'png')
            })
        
        if 'webhook' in settings:
            payload['webhook'] = settings['webhook']
        
        return payload
    
    def upscale_url(self, url: str, mode: str, settings: Dict) -> Optional[bytes]:
        """Upscale image from direct URL via ClarityAI API."""
        try:
            is_video = url.lower().endswith(('.mp4', '.webm', '.mov', '.avi'))
            payload = self.build_request_payload(mode, None, settings, is_video, direct_url=url)
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            print(f"  Sending {url} to API with mode '{mode}'...")
            response = requests.post(
                self.API_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=300
            )
            
            if response.status_code == 200:
                resp_json = response.json()
                # API returns 'message' field with image URL for crystal mode
                img_url = resp_json.get('message') or resp_json.get('image')
                if img_url:
                    print(f"  Downloading from: {img_url}")
                    img_response = requests.get(img_url, timeout=60)
                    if img_response.status_code == 200:
                        return img_response.content
                    else:
                        print(f"✗ Failed to download image: {img_response.status_code}")
                        return None
                else:
                    print(f"✗ No image URL in response: {resp_json}")
                    return None
            else:
                print(f"✗ API error ({response.status_code}): {response.text}")
                return None
        
        except Exception as e:
            print(f"✗ Error processing {url}: {e}")
            return None
    
    def upscale_file(self, file_path: Path, mode: str, settings: Dict) -> Optional[bytes]:
        """Upscale single file via ClarityAI API."""
        try:
            is_video = self.is_video(file_path)
            payload = self.build_request_payload(mode, file_path, settings, is_video)
            
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}'
            }
            
            print(f"  Sending to API with mode '{mode}'...")
            response = requests.post(
                self.API_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=300
            )
            
            if response.status_code == 200:
                resp_json = response.json()
                # API returns 'message' field with image URL for crystal mode
                img_url = resp_json.get('message') or resp_json.get('image')
                if img_url:
                    print(f"  Downloading from: {img_url}")
                    img_response = requests.get(img_url, timeout=60)
                    if img_response.status_code == 200:
                        return img_response.content
                    else:
                        print(f"✗ Failed to download image: {img_response.status_code}")
                        return None
                else:
                    print(f"✗ No image URL in response: {resp_json}")
                    return None
            else:
                print(f"✗ API error ({response.status_code}): {response.text}")
                return None
        
        except Exception as e:
            print(f"✗ Error processing {file_path.name}: {e}")
            return None
    
    def save_upscaled(self, upscaled_data: bytes, original_path: Path, suffix: str = '') -> bool:
        """Save upscaled file to output directory."""
        try:
            name = original_path.stem + suffix + original_path.suffix
            output_path = self.output_dir / name
            with open(output_path, 'wb') as f:
                f.write(upscaled_data)
            return True
        except Exception as e:
            print(f"✗ Failed to save {original_path.name}: {e}")
            return False
    
    def process_files(self, files: List[Path], urls: List[str], mode: str, settings: Dict, batch_delay: float = 1.0):
        """Process multiple files and URLs with optional delay between requests."""
        if not files and not urls:
            print("No files or URLs to process.")
            return
        
        total = len(files) + len(urls)
        successful = 0
        failed = 0
        
        print(f"\nProcessing {len(files)} file(s) + {len(urls)} URL(s) with mode '{mode}'...")
        print(f"Settings: {json.dumps(settings, indent=2)}")
        print(f"Output: {self.output_dir.absolute()}\n")
        
        # Process local files
        for idx, file_path in enumerate(files, 1):
            print(f"[{idx}/{total}] Processing: {file_path.name}")
            
            upscaled = self.upscale_file(file_path, mode, settings)
            
            if upscaled:
                if self.save_upscaled(upscaled, file_path):
                    print(f"      ✓ Saved to {self.output_dir / file_path.name}")
                    successful += 1
                else:
                    failed += 1
            else:
                failed += 1
            
            # Add delay between requests to avoid rate limiting
            if idx < total:
                time.sleep(batch_delay)
        
        # Process URLs
        for idx, url in enumerate(urls, len(files) + 1):
            print(f"[{idx}/{total}] Processing: {url}")
            
            upscaled = self.upscale_url(url, mode, settings)
            
            if upscaled:
                # Extract filename from URL or use hash-based name
                import hashlib
                url_filename = url.split('/')[-1].split('?')[0]
                if not url_filename or url_filename == 'images':
                    # Use hash of URL + index for unique names
                    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                    url_filename = f"upscaled_{idx}_{url_hash}.png"
                try:
                    output_path = self.output_dir / url_filename
                    with open(output_path, 'wb') as f:
                        f.write(upscaled)
                    print(f"      ✓ Saved to {output_path}")
                    successful += 1
                except Exception as e:
                    print(f"✗ Failed to save {url_filename}: {e}")
                    failed += 1
            else:
                failed += 1
            
            # Add delay between requests to avoid rate limiting
            if idx < total:
                time.sleep(batch_delay)
        
        print(f"\n{'='*50}")
        print(f"Complete: {successful} succeeded, {failed} failed")
        print(f"Output directory: {self.output_dir.absolute()}")


def load_settings(settings_file: Optional[str]) -> Dict:
    """Load settings from JSON file or return defaults."""
    defaults = {
        'creativity': 0
    }
    
    if settings_file and Path(settings_file).exists():
        try:
            with open(settings_file) as f:
                custom = json.load(f)
                defaults.update(custom)
                print(f"Loaded settings from {settings_file}")
        except Exception as e:
            print(f"⚠ Failed to load settings file: {e}. Using defaults.")
    
    return defaults


def main():
    parser = argparse.ArgumentParser(
        description="Upscale images/videos using ClarityAI API with multiple modes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Modes:
  crystal       - High-precision upscaling for all images
  crystal-video - High-precision video upscaling
  clarity       - Classic with fine-grained control (creativity, resemblance, dynamic, fractality)
  clarity-pro   - Next-gen for portraits & skin

Examples:
  # Local files
  python upscale_clarity_api.py --key KEY --mode crystal image.jpg
  python upscale_clarity_api.py --key KEY --mode clarity-pro --scale 4 ./images
  
  # Direct URLs
  python upscale_clarity_api.py --key KEY --mode crystal https://example.com/image.jpg
  
  # Txt file with URLs (one per line)
  python upscale_clarity_api.py --key KEY --mode crystal urls.txt
  
  # Mixed
  python upscale_clarity_api.py --key KEY image.jpg ./folder https://example.com/pic.jpg urls.txt
  
  # With settings
  python upscale_clarity_api.py --key KEY --settings config.json ./folder1 ./folder2

Settings JSON format:
  {
    "mode": "crystal",
    "scale_factor": 2,
    "creativity": 0,
    "output_format": "jpg"
  }
        """
    )
    
    parser.add_argument('inputs', nargs='+', help='Image/video files, folders, URLs, or txt files with URLs (one per line)')
    parser.add_argument('--key', help='ClarityAI API key (can be in settings JSON)')
    parser.add_argument('--mode', default='crystal', choices=list(ClarityAIUpscaler.MODES.keys()), 
                        help='Upscaling mode (default: crystal)')
    parser.add_argument('--output', default='upscaled_output', help='Output directory')
    parser.add_argument('--settings', help='JSON settings file')
    parser.add_argument('--scale', type=int, dest='scale_factor', help='Scale factor (1-200 for crystal, 2-16 for clarity)')
    parser.add_argument('--creativity', type=int, help='Creativity level (-10 to 10)')
    parser.add_argument('--resemblance', type=int, help='Resemblance (clarity mode only, -10 to 10)')
    parser.add_argument('--dynamic', type=int, help='Dynamic (clarity mode only, -10 to 10)')
    parser.add_argument('--fractality', type=int, help='Fractality (clarity mode only, -10 to 10)')
    parser.add_argument('--style', choices=['default', 'portrait', 'anime'], 
                        help='Style (clarity mode only)')
    parser.add_argument('--prompt', help='Custom prompt (clarity mode only)')
    parser.add_argument('--format', dest='output_format', choices=['jpg', 'png'], 
                        help='Output format')
    parser.add_argument('--target-mp', type=float, dest='target_megapixels',
                        help='Target megapixels (crystal mode only, 0.001-1500)')
    parser.add_argument('--webhook', help='Webhook URL for async results')
    parser.add_argument('--delay', type=float, default=1.0, 
                        help='Delay between API requests in seconds (default: 1.0)')
    parser.add_argument('--github-pages-url', default='https://humanitiesclinic.github.io/upscaler',
                        help='GitHub Pages base URL for hosting images (default: https://humanitiesclinic.github.io/upscaler)')
    
    # Use parse_known_args to ignore unknown CLI arguments
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"  ⚠ Ignoring unknown arguments: {unknown}")
    
    # Load settings
    settings = load_settings(args.settings)
    settings['mode'] = args.mode
    
    # Override with command-line arguments (CLI takes precedence)
    if args.scale_factor:
        settings['scale_factor'] = args.scale_factor
    if args.creativity is not None:
        settings['creativity'] = args.creativity
    if args.resemblance is not None:
        settings['resemblance'] = args.resemblance
    if args.dynamic is not None:
        settings['dynamic'] = args.dynamic
    if args.fractality is not None:
        settings['fractality'] = args.fractality
    if args.style:
        settings['style'] = args.style
    if args.prompt:
        settings['prompt'] = args.prompt
    if args.output_format:
        settings['output_format'] = args.output_format
    if args.target_megapixels:
        settings['target_megapixels'] = args.target_megapixels
    if args.webhook:
        settings['webhook'] = args.webhook
    
    # Get API key from CLI or settings
    api_key = args.key or settings.get('key')
    if not api_key:
        print("✗ API key required: use --key or set 'key' in settings JSON")
        sys.exit(1)
    
    # Initialize upscaler
    upscaler = ClarityAIUpscaler(api_key, settings.get('output', args.output), args.github_pages_url)
    
    # Collect and process files and URLs
    file_type = 'video' if args.mode == 'crystal-video' else 'image'
    files, urls = upscaler.collect_inputs(args.inputs, file_type)
    upscaler.process_files(files, urls, args.mode, settings, args.delay)


if __name__ == '__main__':
    main()
