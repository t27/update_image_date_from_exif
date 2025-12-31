import os
import shutil
import pathlib
import datetime
import time
import subprocess
import argparse
import exiftool # Requires: pip3 install PyExifTool

# --- Configuration ---
INPUT_EXTENSIONS = {'.jpg', '.jpeg', '.cr3', '.hif', '.heic'}

def parse_offset(offset_str):
    """
    Parses a timezone offset string (e.g., '+09:00', '-05:00', '+09').
    Returns a datetime.timezone object.
    """
    if not offset_str: return None
    try:
        offset_str = str(offset_str).strip().strip('\x00')
        if not offset_str: return None
        
        # Handle format "+09:00" or "+09"
        sign = -1 if offset_str.startswith('-') else 1
        if offset_str.startswith('+') or offset_str.startswith('-'):
            offset_str = offset_str[1:]
        
        parts = offset_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
        
        return datetime.timezone(datetime.timedelta(hours=sign*hours, minutes=sign*minutes))
    except (ValueError, IndexError):
        return None

def get_timestamp_from_metadata(tags):
    """
    Looks for the specific EXIF tags in the ExifTool output dictionary.
    ExifTool keys usually look like 'EXIF:DateTimeOriginal' or 'QuickTime:CreateDate'.
    """
    
    # Priority list of date fields to look for
    date_candidates = [
        'EXIF:DateTimeOriginal',
        'EXIF:DateTimeDigitized',
        # Fallback for CR3/HEIC if EXIF is missing (common in video/container formats)
        'QuickTime:CreationDate', 
        'QuickTime:CreateDate'
    ]
    
    # Priority list of offset fields
    offset_candidates = [
        'EXIF:OffsetTimeOriginal',
        'EXIF:OffsetTimeDigitized',
        'EXIF:OffsetTime'
    ]

    date_str = None
    used_date_tag = None

    # 1. Find the first available Date
    for tag in date_candidates:
        if tag in tags:
            date_str = str(tags[tag])
            used_date_tag = tag
            break
            
    if not date_str:
        return None

    # 2. Try to find an Offset
    tz = None
    for tag in offset_candidates:
        if tag in tags:
            tz = parse_offset(tags[tag])
            if tz: break
    
    try:
        # ExifTool usually returns "YYYY:MM:DD HH:MM:SS"
        # Sometimes it might return "YYYY:MM:DD HH:MM:SS+09:00" if it's smart
        
        # Take first 19 chars to get the clean date time
        clean_date_str = date_str[:19]
        dt_naive = datetime.datetime.strptime(clean_date_str, '%Y:%m:%d %H:%M:%S')
        
        if tz:
            # We found a specific offset tag
            dt_aware = dt_naive.replace(tzinfo=tz)
            return dt_aware.timestamp()
        else:
            # Check if the date string itself contained a timezone (e.g. +09:00 at the end)
            if len(date_str) > 19:
                potential_offset = date_str[19:]
                tz_embedded = parse_offset(potential_offset)
                if tz_embedded:
                    dt_aware = dt_naive.replace(tzinfo=tz_embedded)
                    return dt_aware.timestamp()

            # Fallback: Assume Local Computer Time
            return time.mktime(dt_naive.timetuple())

    except ValueError as e:
        print(f"    Error parsing date '{date_str}': {e}")
        return None

def set_macos_creation_time(path, timestamp):
    """
    Sets the creation time (birthtime) on macOS using 'SetFile'.
    """
    # 1. Update Standard Modified/Access time
    try:
        os.utime(path, (timestamp, timestamp))
    except Exception as e:
        print(f"  Warning: Could not set modification time: {e}")

    # 2. Update macOS specific 'Creation Date'
    try:
        dt_local = datetime.datetime.fromtimestamp(timestamp)
        date_str = dt_local.strftime('%m/%d/%Y %H:%M:%S')
        subprocess.run(['SetFile', '-d', date_str, path], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("  Warning: 'SetFile' failed. Is Xcode CLI installed?")
    except FileNotFoundError:
        print("  Warning: 'SetFile' command not found.")

def process_images(input_dir, output_dir):
    input_path = pathlib.Path(input_dir)
    output_path = pathlib.Path(output_dir)
    
    if not output_path.exists():
        os.makedirs(output_path)
        print(f"Created output directory: {output_path}")

    # Gather files first
    files_to_process = []
    for file_p in input_path.iterdir():
        if file_p.is_file() and file_p.suffix.lower() in INPUT_EXTENSIONS:
            files_to_process.append(file_p)

    print(f"Found {len(files_to_process)} files. Starting ExifTool...")

    # Start ExifTool once (much faster than starting it per file)
    with exiftool.ExifToolHelper() as et:
        for file_p in files_to_process:
            print(f"Processing: {file_p.name}")
            dest_file = output_path / file_p.name
            
            # 1. Copy File first
            shutil.copy2(file_p, dest_file)
            
            try:
                # 2. Read Metadata using ExifTool
                # parsing the destination file is safer to ensure we are working on the final object
                # but reading source is fine too.
                metadata_list = et.get_metadata(str(file_p))
                
                if metadata_list:
                    tags = metadata_list[0] # get_metadata returns a list
                    
                    # 3. Calculate Timestamp
                    timestamp = get_timestamp_from_metadata(tags)
                    
                    # 4. Update Time
                    if timestamp:
                        set_macos_creation_time(str(dest_file), timestamp)
                        print(f"  -> Date updated.")
                    else:
                        print(f"  -> No valid EXIF dates found.")
                else:
                    print("  -> Could not read metadata.")
                    
            except Exception as e:
                print(f"  Error processing {file_p.name}: {e}")

    print("Done.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy images and set macOS creation time from EXIF metadata")
    default_input = './input1'
    default_output = './output1'
    parser.add_argument('-i', '--input', dest='input_dir', default=default_input,
                        help='Input directory containing images (default: %(default)s)')
    parser.add_argument('-o', '--output', dest='output_dir', default=default_output,
                        help='Output directory to copy files to (default: %(default)s)')

    args = parser.parse_args()
    input_folder = args.input_dir
    output_folder = args.output_dir

    if not os.path.exists(input_folder):
        print(f"Input folder not found: {input_folder}")
        parser.exit(2)

    process_images(input_folder, output_folder)