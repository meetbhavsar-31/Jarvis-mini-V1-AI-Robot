"""
diagnose_known_faces.py
-------------------------
Run this from your project root (same place as fix_known_faces.py).
Reproduces face_recognition's exact loading steps one at a time, printing
what's actually happening at each stage -- so we can see EXACTLY which
property (mode, shape, dtype, contiguity) is wrong, instead of guessing.

USAGE:
  python diagnose_known_faces.py
"""

import os
import numpy as np
from PIL import Image

KNOWN_FACES_DIR = "known_faces"

def diagnose_file(path):
    print(f"\n--- {os.path.basename(path)} ---")

    # Step 1: raw PIL open, no conversion
    try:
        im_raw = Image.open(path)
        print(f"  Raw PIL mode: {im_raw.mode}, size: {im_raw.size}")
    except Exception as e:
        print(f"  FAILED at raw PIL open: {e}")
        return

    # Step 2: this is EXACTLY what face_recognition.load_image_file() does internally
    try:
        im_rgb = im_raw.convert("RGB")
        arr = np.array(im_rgb)
        print(f"  After .convert('RGB') -> np.array: shape={arr.shape}, dtype={arr.dtype}, "
              f"contiguous={arr.flags['C_CONTIGUOUS']}")
    except Exception as e:
        print(f"  FAILED at convert/array step: {e}")
        return

    # Step 3: try the actual face_recognition call chain
    try:
        import face_recognition
        loaded = face_recognition.load_image_file(path)
        print(f"  face_recognition.load_image_file() OK: shape={loaded.shape}, dtype={loaded.dtype}, "
              f"contiguous={loaded.flags['C_CONTIGUOUS']}")
    except Exception as e:
        print(f"  FAILED at face_recognition.load_image_file(): {e}")
        return

    # Step 4: the actual step that raises "Unsupported image type"
    try:
        encodings = face_recognition.face_encodings(loaded)
        if encodings:
            print(f"  face_encodings() OK -- found {len(encodings)} face(s). This file is fine.")
        else:
            print(f"  face_encodings() ran with NO ERROR but found 0 faces -- "
                  f"image loads fine, but no face detected in it (different problem: bad photo, not a format bug).")
    except Exception as e:
        print(f"  FAILED at face_recognition.face_encodings(): {e}")
        print(f"  ^ THIS is your real error source, not the file format.")

def main():
    if not os.path.exists(KNOWN_FACES_DIR):
        print(f"'{KNOWN_FACES_DIR}' not found in current directory: {os.getcwd()}")
        return

    print(f"Diagnosing images in: {os.path.abspath(KNOWN_FACES_DIR)}")
    try:
        import face_recognition
        print(f"face_recognition module loaded from: {face_recognition.__file__}")
    except ImportError:
        print("face_recognition is NOT installed in this Python environment!")
        print("This might mean you're running this diagnostic in a different environment than your server.")
        return

    for filename in os.listdir(KNOWN_FACES_DIR):
        if filename.lower().endswith((".jpg", ".jpeg", ".png")):
            diagnose_file(os.path.join(KNOWN_FACES_DIR, filename))

if __name__ == "__main__":
    main()
